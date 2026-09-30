from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from backend.app.services.bot_bridge import BotLeadNotFoundError, update_bot_stage

pytestmark = pytest.mark.usefixtures("db_available")

WA = "79990000101@c.us"


async def _insert_lead(session, whatsapp_id: str = WA, stage: str = "НОВЫЙ_ЛИД") -> None:
    await session.execute(
        text(
            "INSERT INTO knewit_leads (whatsapp_id, name, current_stage, status)"
            " VALUES (:wa, 'Bridge Test', :stage, 'ACTIVE')"
        ),
        {"wa": whatsapp_id, "stage": stage},
    )


async def test_update_moves_stage_and_writes_event(tx_session):
    await _insert_lead(tx_session)
    admin_id = uuid.uuid4()

    messages_before = (
        await tx_session.execute(text("SELECT COUNT(*) FROM knewit_messages"))
    ).scalar()
    followups_before = (
        await tx_session.execute(text("SELECT COUNT(*) FROM knewit_followups"))
    ).scalar()

    moved = await update_bot_stage(tx_session, WA, "ЗАПИСЬ", admin_id)
    assert moved is True
    await tx_session.flush()

    lead = (
        (
            await tx_session.execute(
                text(
                    "SELECT current_stage, previous_stage, status, name"
                    " FROM knewit_leads WHERE whatsapp_id = :wa"
                ),
                {"wa": WA},
            )
        )
        .mappings()
        .one()
    )
    assert lead["current_stage"] == "ЗАПИСЬ"
    assert lead["previous_stage"] == "НОВЫЙ_ЛИД"
    # Nothing else on the lead row changed.
    assert lead["status"] == "ACTIVE"
    assert lead["name"] == "Bridge Test"

    events = (
        (
            await tx_session.execute(
                text(
                    "SELECT event_type, from_stage, to_stage, payload"
                    " FROM knewit_events WHERE whatsapp_id = :wa"
                ),
                {"wa": WA},
            )
        )
        .mappings()
        .all()
    )
    assert len(events) == 1
    assert events[0]["event_type"] == "manual_stage_change"
    assert events[0]["from_stage"] == "НОВЫЙ_ЛИД"
    assert events[0]["to_stage"] == "ЗАПИСЬ"
    assert events[0]["payload"]["user_id"] == str(admin_id)

    # Bridge touched nothing else.
    assert (await tx_session.execute(text("SELECT COUNT(*) FROM knewit_messages"))).scalar() == (
        messages_before
    )
    assert (
        await tx_session.execute(text("SELECT COUNT(*) FROM knewit_followups"))
    ).scalar() == followups_before
    other = (
        await tx_session.execute(
            text("SELECT current_stage FROM knewit_leads WHERE whatsapp_id = '77010000001@c.us'")
        )
    ).scalar()
    assert other == "НОВЫЙ_ЛИД"


async def test_noop_when_stage_unchanged(tx_session):
    await _insert_lead(tx_session)
    moved = await update_bot_stage(tx_session, WA, "НОВЫЙ_ЛИД", uuid.uuid4())
    assert moved is False
    count = (
        await tx_session.execute(
            text("SELECT COUNT(*) FROM knewit_events WHERE whatsapp_id = :wa"), {"wa": WA}
        )
    ).scalar()
    assert count == 0


async def test_missing_lead_raises(tx_session):
    with pytest.raises(BotLeadNotFoundError):
        await update_bot_stage(tx_session, "79990000999@c.us", "ЗАПИСЬ", uuid.uuid4())
