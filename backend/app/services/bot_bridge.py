from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MANUAL_STAGE_CHANGE_EVENT = "manual_stage_change"


class BotLeadNotFoundError(LookupError):
    """Raised when the target lead does not exist in knewit_leads."""


async def update_bot_stage(
    session: AsyncSession,
    whatsapp_id: str,
    stage_key: str,
    changed_by: uuid.UUID | None,
) -> bool:
    """Push a manager-driven stage change into the bot tables (D3).

    Updates ``knewit_leads.current_stage``/``previous_stage`` and appends a
    ``manual_stage_change`` row to ``knewit_events`` in the caller's
    transaction (no commit here). Returns True when something changed,
    False when the lead already sits on ``stage_key``.

    This module is the ONLY place allowed to write to ``knewit_*`` tables.
    """
    row = (
        await session.execute(
            text(
                "SELECT current_stage FROM knewit_leads"
                " WHERE whatsapp_id = :whatsapp_id FOR UPDATE"
            ),
            {"whatsapp_id": whatsapp_id},
        )
    ).one_or_none()
    if row is None:
        raise BotLeadNotFoundError(f"Bot lead not found: {whatsapp_id}")
    from_stage: str | None = row[0]
    if from_stage == stage_key:
        return False

    now = datetime.now(UTC)
    await session.execute(
        text(
            "UPDATE knewit_leads SET previous_stage = current_stage,"
            " current_stage = :stage_key, updated_at = :now"
            " WHERE whatsapp_id = :whatsapp_id"
        ),
        {"stage_key": stage_key, "now": now, "whatsapp_id": whatsapp_id},
    )
    payload = {"user_id": str(changed_by) if changed_by is not None else None}
    await session.execute(
        text(
            "INSERT INTO knewit_events"
            " (whatsapp_id, event_type, from_stage, to_stage, payload, created_at)"
            " VALUES (:whatsapp_id, :event_type, :from_stage, :to_stage,"
            " CAST(:payload AS jsonb), :now)"
        ),
        {
            "whatsapp_id": whatsapp_id,
            "event_type": MANUAL_STAGE_CHANGE_EVENT,
            "from_stage": from_stage,
            "to_stage": stage_key,
            "payload": _json(payload),
            "now": now,
        },
    )
    logger.info(
        "bot stage updated whatsapp_id=%s from=%s to=%s", whatsapp_id, from_stage, stage_key
    )
    return True


def _json(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)
