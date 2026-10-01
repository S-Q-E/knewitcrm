from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .event_bus import bus

logger = logging.getLogger(__name__)

BusEvent = dict[str, Any]


async def notify(
    session: AsyncSession,
    user_ids: list[uuid.UUID],
    type: str,
    payload: dict[str, Any] | None = None,
) -> list[BusEvent]:
    """Create notifications, one row per user. Returns pending bus events.

    Dedupe is enforced by the database: ``dedupe_key`` (taken from the
    payload, stored in its own column) has a partial unique index over
    ``(user_id, type, dedupe_key) WHERE read_at IS NULL``. Concurrent
    inserts serialize on the index; losers hit ``ON CONFLICT DO NOTHING``.
    Rows without a key always insert (NULLs never conflict); read rows no
    longer block new ones.

    Nothing is published here: the caller publishes the returned events
    AFTER its commit, so subscribers never refetch ghosts. No commit here.
    """
    payload = dict(payload or {})
    raw_key = payload.get("dedupe_key")
    key = str(raw_key) if raw_key is not None else None
    pending: list[BusEvent] = []
    for user_id in dict.fromkeys(user_ids):
        inserted = (
            await session.execute(
                text(
                    "INSERT INTO crm_notifications (id, user_id, type, payload, dedupe_key)"
                    " VALUES (gen_random_uuid(), :user_id, :type,"
                    " CAST(:payload AS jsonb), :key)"
                    " ON CONFLICT DO NOTHING RETURNING id"
                ),
                {
                    "user_id": user_id,
                    "type": type,
                    "payload": _json(payload),
                    "key": key,
                },
            )
        ).scalar_one_or_none()
        if inserted is not None:
            pending.append(
                {
                    "type": "notification",
                    "data": {"user_id": str(user_id), "type": type, "payload": payload},
                }
            )
    if pending:
        logger.info("notifications created type=%s count=%d", type, len(pending))
    return pending


def publish_pending(events: Iterable[BusEvent]) -> None:
    """Fan out events collected by notify() — call only after commit."""
    for event in events:
        bus.publish(event["type"], event["data"])


def _json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)


async def active_managers(session: AsyncSession) -> list[tuple[uuid.UUID, str]]:
    """Active managers ordered deterministically (for round-robin)."""
    from sqlalchemy import select

    from ..models import ROLE_MANAGER, CrmUser

    rows = (
        await session.execute(
            select(CrmUser.id, CrmUser.name)
            .where(CrmUser.role == ROLE_MANAGER, CrmUser.is_active.is_(True))
            .order_by(CrmUser.created_at, CrmUser.id)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]
