from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .notifications import active_managers

logger = logging.getLogger(__name__)

SETTING_ASSIGNMENT = "deal_assignment"

MODE_UNASSIGNED = "unassigned"
MODE_ROUND_ROBIN = "round_robin"


async def get_assignment_mode(session: AsyncSession) -> str:
    row = (
        await session.execute(
            text("SELECT value FROM crm_settings WHERE key = :key"), {"key": SETTING_ASSIGNMENT}
        )
    ).scalar_one_or_none()
    if isinstance(row, dict) and row.get("mode") == MODE_ROUND_ROBIN:
        return MODE_ROUND_ROBIN
    return MODE_UNASSIGNED


async def pick_assignee(session: AsyncSession) -> uuid.UUID | None:
    """Round-robin pick among active managers; None when disabled or empty.

    The settings row is locked (SELECT ... FOR UPDATE, seeded by migration
    ``0013_round_robin``) so concurrent picks serialize: read, rotate and
    store happen atomically within the caller's transaction. No commit here.
    """
    row = (
        await session.execute(
            text("SELECT value FROM crm_settings WHERE key = :key FOR UPDATE"),
            {"key": SETTING_ASSIGNMENT},
        )
    ).scalar_one_or_none()
    if not (isinstance(row, dict) and row.get("mode") == MODE_ROUND_ROBIN):
        return None
    managers = await active_managers(session)
    if not managers:
        return None
    last_index = row.get("last_index")
    if not isinstance(last_index, int):
        last_index = -1
    # The roster may change; rotate by position, not by stored user.
    next_index = (last_index + 1) % len(managers)
    picked = managers[next_index][0]
    await session.execute(
        text(
            "INSERT INTO crm_settings (key, value) VALUES (:key, CAST(:value AS jsonb))"
            " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {
            "key": SETTING_ASSIGNMENT,
            "value": json.dumps({"mode": MODE_ROUND_ROBIN, "last_index": next_index}),
        },
    )
    logger.info("round-robin assigned user=%s", picked)
    return picked
