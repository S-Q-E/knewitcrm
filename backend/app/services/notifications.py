from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CrmNotification

logger = logging.getLogger(__name__)


async def notify(
    session: AsyncSession,
    user_ids: list[uuid.UUID],
    type: str,
    payload: dict[str, Any] | None = None,
) -> int:
    """Create notifications. Skips users with an unread duplicate dedupe key.

    Callers put ``dedupe_key`` into the payload for repeatable events
    (e.g. daily overdue reminders); without it every call notifies.
    Returns the number of created rows.
    """
    payload = dict(payload or {})
    dedupe_key = payload.get("dedupe_key")
    created = 0
    for user_id in dict.fromkeys(user_ids):
        if dedupe_key is not None and await _has_unread_dedupe(
            session, user_id, type, str(dedupe_key)
        ):
            continue
        session.add(CrmNotification(user_id=user_id, type=type, payload=payload))
        created += 1
    if created:
        await session.flush()
        logger.info("notifications created type=%s count=%d", type, created)
    return created


async def _has_unread_dedupe(
    session: AsyncSession, user_id: uuid.UUID, type: str, dedupe_key: str
) -> bool:
    row = (
        await session.execute(
            select(CrmNotification.id).where(
                CrmNotification.user_id == user_id,
                CrmNotification.type == type,
                CrmNotification.read_at.is_(None),
                CrmNotification.payload["dedupe_key"].astext == dedupe_key,
            )
        )
    ).first()
    return row is not None


async def active_managers(session: AsyncSession) -> list[tuple[uuid.UUID, str]]:
    """Active managers ordered deterministically (for round-robin)."""
    from ..models import ROLE_MANAGER, CrmUser

    rows = (
        await session.execute(
            select(CrmUser.id, CrmUser.name)
            .where(CrmUser.role == ROLE_MANAGER, CrmUser.is_active.is_(True))
            .order_by(CrmUser.created_at, CrmUser.id)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]
