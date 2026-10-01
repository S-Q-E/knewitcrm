from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import Settings
from ..models import CrmOutbox
from ..services.bot_bridge import insert_outgoing_message
from ..services.event_bus import bus
from ..services.notifications import notify

logger = logging.getLogger(__name__)

OUTBOX_LOCK_KEY = 91030003
OUTBOX_BATCH_SIZE = 50
OUTBOX_MAX_ATTEMPTS = 5
OUTBOX_HTTP_TIMEOUT_SECONDS = 10.0

# A row stuck in 'sending' longer than this never got an outcome (the worker
# died mid-flight or the connection dropped after n8n received the payload).
# It becomes 'failed' without auto-retry: redelivery may double-send.
OUTBOX_STALE_SENDING_SECONDS = 120
STALE_SENDING_ERROR = "delivery state unknown, check WhatsApp"

N8N_SECRET_HEADER = "X-CRM-Secret"

# sender(outbox_id=..., whatsapp_id=..., text=...) -> n8n response payload.
Sender = Callable[..., Awaitable[dict[str, Any]]]


class OutboxConfigError(RuntimeError):
    """n8n webhook URL/secret are not configured."""


class N8nError(RuntimeError):
    """n8n rejected the message or answered with an HTTP error."""


def _retry_delay(attempts: int) -> timedelta:
    """Exponential backoff: 1m, 2m, 4m, 8m, capped at 1h."""
    return min(timedelta(minutes=2 ** (attempts - 1)), timedelta(hours=1))


def is_retryable(exc: BaseException) -> bool:
    """True only when the request provably never reached n8n.

    Connection setup failures (refused/reset/DNS via ConnectError, connect
    timeouts) are safe to retry: n8n could not have received the payload.
    Anything later (read/write timeouts, HTTP errors, rejections) is
    ambiguous — the message may already be delivered — so the row fails
    immediately and waits for a manual retry.
    """
    return isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout)


async def post_to_n8n(
    settings: Settings, *, outbox_id: uuid.UUID, whatsapp_id: str, text: str
) -> dict[str, Any]:
    """POST one queued message to the n8n send webhook (D6).

    ``outbox_id`` travels in the payload so n8n can dedupe redeliveries.
    Returns the decoded payload. Transport-level httpx errors propagate
    unchanged so the worker can tell "never reached n8n" apart from
    ambiguous failures; HTTP errors, non-JSON bodies and explicit
    ``{"ok": false}`` rejections raise ``N8nError``.
    """
    url = settings.n8n_send_webhook_url
    secret = settings.n8n_webhook_secret
    if not url or not secret:
        raise OutboxConfigError("N8N_SEND_WEBHOOK_URL / N8N_WEBHOOK_SECRET are not configured")
    async with httpx.AsyncClient(timeout=OUTBOX_HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(
            url,
            headers={N8N_SECRET_HEADER: secret},
            json={"outbox_id": str(outbox_id), "whatsapp_id": whatsapp_id, "text": text},
        )
    if response.status_code >= 400:
        raise N8nError(f"n8n webhook HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise N8nError("n8n webhook returned a non-JSON body") from exc
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise N8nError(f"n8n rejected the message: {payload!r}")
    return payload


async def run_outbox_cycle(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    sender: Sender | None = None,
) -> dict[str, int] | None:
    """Send due queued outbox rows. Returns None when the lock is held."""
    send: Sender = sender or (lambda **kwargs: post_to_n8n(settings, **kwargs))
    claimed: list[tuple[uuid.UUID, str, str, uuid.UUID | None, int]] = []
    async with session_factory() as session:
        async with session.begin():
            got_lock = (
                await session.execute(
                    text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": OUTBOX_LOCK_KEY}
                )
            ).scalar()
            if not got_lock:
                logger.debug("outbox skipped: lock held by another instance")
                return None
            stats = {
                "claimed": 0,
                "sent": 0,
                "failed": 0,
                "pending_retry": 0,
                "skipped": 0,
                "reaped": 0,
            }
            stats["reaped"] = await _reap_stale_sending(session)
            rows = (
                (
                    await session.execute(
                        select(CrmOutbox)
                        .where(
                            CrmOutbox.status == "queued",
                            (CrmOutbox.next_attempt_at.is_(None))
                            | (CrmOutbox.next_attempt_at <= datetime.now(UTC)),
                        )
                        .order_by(CrmOutbox.created_at, CrmOutbox.id)
                        .limit(OUTBOX_BATCH_SIZE)
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )
            now = datetime.now(UTC)
            for row in rows:
                row.status = "sending"
                row.claimed_at = now
                claimed.append((row.id, row.whatsapp_id, row.body, row.sent_by, row.attempts))
            stats["claimed"] = len(claimed)
    # HTTP calls run outside the claim transaction; each row already carries
    # status='sending', so a concurrent instance never picks it up again.
    for outbox_id, whatsapp_id, body, sent_by, _attempts in claimed:
        try:
            try:
                payload = await send(outbox_id=outbox_id, whatsapp_id=whatsapp_id, text=body)
            except Exception as exc:  # noqa: BLE001 - every failure mode lands on the row
                await _apply_failure(session_factory, outbox_id, sent_by, whatsapp_id, exc, stats)
            else:
                await _apply_success(
                    session_factory, outbox_id, sent_by, whatsapp_id, body, payload, stats
                )
        except Exception:  # noqa: BLE001 - one poisoned row must not stop the cycle
            stats["skipped"] += 1
            logger.exception("outbox %s outcome failed", outbox_id)
    logger.info("outbox cycle done %s", stats)
    return stats


async def _reap_stale_sending(session: AsyncSession) -> int:
    """Fail 'sending' rows whose outcome was lost (worker died mid-flight).

    No auto-retry: the payload may have reached n8n, so redelivery could
    double-send. The author is notified like for any other terminal failure.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=OUTBOX_STALE_SENDING_SECONDS)
    rows = (
        (
            await session.execute(
                select(CrmOutbox)
                .where(CrmOutbox.status == "sending", CrmOutbox.claimed_at < cutoff)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.status = "failed"
        row.error = STALE_SENDING_ERROR
        row.next_attempt_at = None
        if row.sent_by is not None:
            await notify(
                session,
                [row.sent_by],
                "outbox_failed",
                {
                    "outbox_id": str(row.id),
                    "whatsapp_id": row.whatsapp_id,
                    "dedupe_key": f"outbox-failed:{row.id}",
                },
            )
    if rows:
        logger.warning("outbox reaped %d stale sending rows", len(rows))
        for row in rows:
            bus.publish(
                "outbox_status",
                {"outbox_id": str(row.id), "whatsapp_id": row.whatsapp_id, "status": "failed"},
            )
    return len(rows)


async def _apply_success(
    session_factory: async_sessionmaker[AsyncSession],
    outbox_id: uuid.UUID,
    sent_by: uuid.UUID | None,
    whatsapp_id: str,
    body: str,
    payload: dict[str, Any],
    stats: dict[str, int],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            updated = (
                await session.execute(
                    text(
                        "UPDATE crm_outbox SET status = 'sent', sent_at = :now,"
                        " provider_message_id = :provider_id, error = NULL,"
                        " claimed_at = NULL"
                        " WHERE id = :id AND status = 'sending'"
                    ),
                    {
                        "now": datetime.now(UTC),
                        "provider_id": payload.get("provider_message_id"),
                        "id": outbox_id,
                    },
                )
            ).rowcount
            if not updated:
                stats["skipped"] += 1
                return
            try:
                async with session.begin_nested():
                    message_id = await insert_outgoing_message(session, whatsapp_id, body)
            except Exception as exc:  # noqa: BLE001 - mirror must not undo the send
                logger.error("outbox %s mirror failed: %s", outbox_id, exc)
                await session.execute(
                    text("UPDATE crm_outbox SET error = :error WHERE id = :id"),
                    {"error": f"mirror_failed: {exc}"[:2000], "id": outbox_id},
                )
            else:
                await session.execute(
                    text("UPDATE crm_outbox SET knewit_message_id = :mid WHERE id = :id"),
                    {"mid": message_id, "id": outbox_id},
                )
            stats["sent"] += 1
    bus.publish(
        "outbox_status",
        {"outbox_id": str(outbox_id), "whatsapp_id": whatsapp_id, "status": "sent"},
    )
    logger.info("outbox sent id=%s whatsapp_id=%s", outbox_id, whatsapp_id)


async def _apply_failure(
    session_factory: async_sessionmaker[AsyncSession],
    outbox_id: uuid.UUID,
    sent_by: uuid.UUID | None,
    whatsapp_id: str,
    exc: Exception,
    stats: dict[str, int],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            row = (
                await session.execute(
                    select(CrmOutbox).where(CrmOutbox.id == outbox_id).with_for_update()
                )
            ).scalar_one_or_none()
            if row is None or row.status != "sending":
                stats["skipped"] += 1
                return
            row.attempts += 1
            row.error = str(exc)[:2000]
            row.claimed_at = None
            failed_now = False
            if is_retryable(exc) and row.attempts < OUTBOX_MAX_ATTEMPTS:
                row.status = "queued"
                row.next_attempt_at = datetime.now(UTC) + _retry_delay(row.attempts)
                stats["pending_retry"] += 1
            else:
                row.status = "failed"
                row.next_attempt_at = None
                stats["failed"] += 1
                failed_now = True
                if sent_by is not None:
                    await notify(
                        session,
                        [sent_by],
                        "outbox_failed",
                        {
                            "outbox_id": str(outbox_id),
                            "whatsapp_id": whatsapp_id,
                            "dedupe_key": f"outbox-failed:{outbox_id}",
                        },
                    )
    if failed_now:
        bus.publish(
            "outbox_status",
            {"outbox_id": str(outbox_id), "whatsapp_id": whatsapp_id, "status": "failed"},
        )
    logger.warning("outbox %s attempt failed: %s", outbox_id, exc)


async def outbox_loop(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    interval_seconds: int = 5,
) -> None:
    """Background loop for lifespan. Never raises; failures are logged."""
    while True:
        try:
            await run_outbox_cycle(session_factory, settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("outbox cycle failed")
        await asyncio.sleep(interval_seconds)
