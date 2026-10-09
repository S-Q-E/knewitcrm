from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from backend.app.services import metrics
from backend.app.services.event_bus import EventBus
from backend.app.services.ops_metrics import ops_gauges
from backend.tests.crm_helpers import engine_factory

pytestmark = pytest.mark.usefixtures("db_available")

PREFIX = "ops-metrics-"


def _parse(lines: list[str]) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in lines:
        key, value = line.rsplit(" ", 1)
        values[key] = float(value)
    return values


async def _cleanup(factory) -> None:
    async with factory() as session:
        await session.execute(
            text("DELETE FROM crm_outbox WHERE whatsapp_id LIKE :p"), {"p": PREFIX + "%"}
        )
        await session.execute(
            text("DELETE FROM crm_conversation_state WHERE whatsapp_id LIKE :p"),
            {"p": PREFIX + "%"},
        )
        await session.commit()


async def test_ops_gauges_report_backlog_and_unanswered(settings):
    engine, factory = engine_factory(settings)
    metrics.reset()
    try:
        async with factory() as session:
            before = _parse(await ops_gauges(session, EventBus()))["crm_unanswered_dialogs"]

        old = datetime.now(UTC) - timedelta(hours=1)
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO crm_outbox (id, whatsapp_id, body, status, created_at)"
                    " VALUES (gen_random_uuid(), :wa, 'x', 'queued', :at)"
                ),
                {"wa": PREFIX + "queued@c.us", "at": old},
            )
            await session.execute(
                text(
                    "INSERT INTO crm_outbox (id, whatsapp_id, body, status, created_at, claimed_at)"
                    " VALUES (gen_random_uuid(), :wa, 'x', 'sending', :at, :at)"
                ),
                {"wa": PREFIX + "sending@c.us", "at": old},
            )
            for wa, paused in ((PREFIX + "open@c.us", False), (PREFIX + "paused@c.us", True)):
                await session.execute(
                    text(
                        "INSERT INTO crm_conversation_state"
                        " (whatsapp_id, bot_paused, last_message_direction, last_message_at)"
                        " VALUES (:wa, :paused, 'in', :at)"
                    ),
                    {"wa": wa, "paused": paused, "at": old},
                )
            await session.commit()

        metrics.mark_cycle("realtime")
        bus_local = EventBus()
        bus_local.subscribe()
        async with factory() as session:
            values = _parse(await ops_gauges(session, bus_local))

        assert values['crm_outbox_oldest_due_seconds{status="queued"}'] >= 3500
        assert values['crm_outbox_oldest_due_seconds{status="sending"}'] >= 3500
        assert values["crm_unanswered_dialogs"] == before + 1
        assert values["crm_sse_subscribers"] == 1
        assert values["crm_realtime_poll_age_seconds"] < 60
    finally:
        await _cleanup(factory)
        metrics.reset()
        await engine.dispose()


def test_cycle_age_is_absent_until_first_success():
    metrics.reset()
    assert metrics.cycle_age_seconds("realtime") is None
    metrics.mark_cycle("realtime")
    age = metrics.cycle_age_seconds("realtime")
    assert age is not None and 0 <= age < 5
    metrics.reset()
    assert metrics.cycle_age_seconds("realtime") is None
