"""Dialogs where the client wrote and nobody answered (P0-5).

One definition shared by the list filter, the per-row flag, the notification
worker and the metrics gauge, so they cannot disagree. Read-only except for
notifications, which go through services/notifications.notify().
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CrmContact, CrmConversationState, CrmDeal, CrmNotification
from .notifications import active_managers, notify

SETTING_KEY = "unanswered_after_minutes"
DEFAULT_MINUTES = 10
MIN_MINUTES = 1
MAX_MINUTES = 1440
NOTIFY_TYPE = "unanswered"
# Only episodes this recent alert. Older unanswered dialogs still appear in the
# filter, but a first run must not flood managers with history.
NOTIFY_WINDOW = timedelta(hours=24)


async def threshold_minutes(session: AsyncSession) -> int:
    value = (
        await session.execute(
            text("SELECT value FROM crm_settings WHERE key = :key"), {"key": SETTING_KEY}
        )
    ).scalar_one_or_none()
    if isinstance(value, int) and not isinstance(value, bool):
        if MIN_MINUTES <= value <= MAX_MINUTES:
            return value
    return DEFAULT_MINUTES


async def cutoff(session: AsyncSession, now: datetime | None = None) -> datetime:
    """Client messages older than this, with no reply, count as unanswered."""
    return (now or datetime.now(UTC)) - timedelta(minutes=await threshold_minutes(session))


def unanswered_clause(cutoff_at: datetime) -> Any:
    return and_(
        CrmConversationState.last_message_direction == "in",
        CrmConversationState.bot_paused.is_(False),
        CrmConversationState.last_message_at < cutoff_at,
    )


def is_unanswered(state: CrmConversationState, cutoff_at: datetime) -> bool:
    return (
        state.last_message_direction == "in"
        and not state.bot_paused
        and state.last_message_at is not None
        and state.last_message_at < cutoff_at
    )


async def notify_unanswered(session: AsyncSession, now: datetime) -> list[dict]:
    """Notify the responsible user about each new unanswered episode.

    An episode is one client message: its dedupe key carries the message time,
    so a new message starts a new episode. The key is checked against all
    notifications, read or not, so a read notification is not repeated every
    cycle. Responsible: the dialog's assignee, else the managed-deal owner,
    else the contact owner; with none, all active managers. Runs under the
    notify worker's advisory lock.
    """
    cut = await cutoff(session, now)
    managed = (
        select(CrmDeal.contact_id, CrmDeal.owner_id.label("deal_owner_id"))
        .where(CrmDeal.deleted_at.is_(None))
        .distinct(CrmDeal.contact_id)
        .order_by(CrmDeal.contact_id, CrmDeal.updated_at.desc(), CrmDeal.id)
        .subquery("md")
    )
    rows = (
        await session.execute(
            select(
                CrmConversationState.whatsapp_id,
                CrmConversationState.last_message_at,
                CrmConversationState.assigned_to,
                managed.c.deal_owner_id,
                CrmContact.owner_id,
            )
            .outerjoin(CrmContact, CrmContact.whatsapp_id == CrmConversationState.whatsapp_id)
            .outerjoin(managed, managed.c.contact_id == CrmContact.id)
            .where(
                unanswered_clause(cut),
                CrmConversationState.last_message_at >= now - NOTIFY_WINDOW,
            )
        )
    ).all()
    if not rows:
        return []

    keys = {wa: f"unanswered:{wa}:{at.isoformat()}" for wa, at, *_ in rows}
    existing = set(
        (
            await session.execute(
                select(CrmNotification.dedupe_key).where(
                    CrmNotification.type == NOTIFY_TYPE,
                    CrmNotification.dedupe_key.in_(list(keys.values())),
                )
            )
        ).scalars()
    )
    managers: list[uuid.UUID] | None = None
    pending: list[dict] = []
    seen: set[str] = set()
    for wa, at, assigned, deal_owner, contact_owner in rows:
        key = keys[wa]
        if key in existing or wa in seen:
            continue
        seen.add(wa)
        owner = assigned or deal_owner or contact_owner
        if owner is not None:
            targets = [owner]
        else:
            if managers is None:
                managers = [user_id for user_id, _ in await active_managers(session)]
            targets = managers
        pending.extend(
            await notify(
                session,
                targets,
                NOTIFY_TYPE,
                {"whatsapp_id": wa, "last_message_at": at.isoformat(), "dedupe_key": key},
            )
        )
    return pending
