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
    """Round-robin pick among active managers; None when disabled or empty."""
    if await get_assignment_mode(session) != MODE_ROUND_ROBIN:
        return None
    managers = await active_managers(session)
    if not managers:
        return None
    row = (
        await session.execute(
            text("SELECT value FROM crm_settings WHERE key = :key"), {"key": SETTING_ASSIGNMENT}
        )
    ).scalar_one_or_none()
    last_index = -1
    if isinstance(row, dict) and isinstance(row.get("last_index"), int):
        last_index = row["last_index"]
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
