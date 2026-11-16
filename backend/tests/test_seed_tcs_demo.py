"""Tests for scripts/seed_tcs_demo.py (protection, idempotency, --reset).

All database work runs inside a rolled-back transaction, so the tests never
leave the TCS funnel or demo rows behind.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import asyncpg
import pytest

from backend.tests.conftest import REPO_ROOT

pytestmark = pytest.mark.usefixtures("migrated")

_SCRIPT = REPO_ROOT / "scripts" / "seed_tcs_demo.py"
_spec = importlib.util.spec_from_file_location("seed_tcs_demo", _SCRIPT)
assert _spec and _spec.loader
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)


def _dsn(settings) -> str:
    url = settings.database_url
    return url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture()
async def conn(settings, db_available):
    connection = await asyncpg.connect(dsn=_dsn(settings))
    try:
        tx = connection.transaction()
        await tx.start()
        try:
            # The shared test DB contains fixture rows with source='whatsapp';
            # wipe the bot slice inside the transaction (rolled back later).
            for table in ("tcs_messages", "tcs_events", "tcs_followups", "tcs_ai_metrics"):
                await connection.execute(f"DELETE FROM {table}")
            await connection.execute("DELETE FROM tcs_leads")
            yield connection
        finally:
            await tx.rollback()  # never leave the TCS funnel or demo rows behind
    finally:
        await connection.close()


async def test_confirm_refuses_without_env():
    assert seed.confirm_error({}) is not None
    assert seed.confirm_error({seed.CONFIRM_ENV: seed.CONFIRM_VALUE}) is None


async def test_schema_check_blocks_whatsapp_rows(conn):
    # Fresh DB path: applies the fixture schema when tcs_leads is missing is
    # covered indirectly — here the table exists, so no schema is applied.
    await conn.execute(
        "INSERT INTO tcs_leads (whatsapp_id, source)"
        " VALUES ($1, 'whatsapp') ON CONFLICT DO NOTHING",
        "tg:111111111",
    )
    error = await seed.schema_error(conn)
    assert error is not None and "Refusing to run" in error

    await conn.execute("DELETE FROM tcs_leads WHERE whatsapp_id = 'tg:111111111'")
    assert await seed.schema_error(conn) is None


async def test_seed_idempotent_and_complete(conn):
    await seed.schema_error(conn)
    first = await seed.run_seed(conn)
    second = await seed.run_seed(conn)

    assert first == second
    assert first["leads"] == 30
    assert first["units"] == 14

    # TCS pipeline is the single default.
    defaults = await conn.fetch("SELECT name FROM crm_pipelines WHERE is_default ORDER BY name")
    assert [row["name"] for row in defaults] == ["TCS Leasing"]

    stages = await conn.fetch(
        "SELECT name, bot_stage_key, kind, bot_status_key FROM crm_stages"
        " WHERE pipeline_id = (SELECT id FROM crm_pipelines WHERE name = 'TCS Leasing')"
        " ORDER BY sort"
    )
    assert [row["name"] for row in stages] == [
        "New inquiry",
        "Qualifying",
        "Unit matched",
        "Viewing scheduled",
        "Viewing confirmed",
        "Viewing done",
        "Application sent",
        "Follow-up",
        "Leased",
        "Lost",
    ]
    won = next(row for row in stages if row["name"] == "Leased")
    assert won["bot_status_key"] == "КЛИЕНТ"
    lost = next(row for row in stages if row["name"] == "Lost")
    assert lost["bot_status_key"] == "ОТКАЗ"

    # unanswered_after_minutes is a JSON number 2 (RECON.md §3).
    raw = await conn.fetchval(
        "SELECT value FROM crm_settings WHERE key = 'unanswered_after_minutes'"
    )
    value = json.loads(raw) if isinstance(raw, str) else raw
    assert value == 2

    # Demo leads: exactly one unanswered dialog (last message 'in', bot live).
    last_directions = await conn.fetch(
        """
        SELECT DISTINCT ON (l.whatsapp_id) l.whatsapp_id, m.direction
        FROM tcs_leads l
        JOIN tcs_messages m ON m.whatsapp_id = l.whatsapp_id
        WHERE l.source = 'demo'
        ORDER BY l.whatsapp_id, m.created_at DESC, m.id DESC
        """
    )
    incoming = [row["whatsapp_id"] for row in last_directions if row["direction"] == "in"]
    assert incoming == ["tg:900000004"]

    # 12 viewings: 9 past + 3 future.
    trials = await conn.fetch(
        "SELECT trial_datetime FROM tcs_leads WHERE source = 'demo' AND trial_datetime IS NOT NULL"
    )
    assert len(trials) == 12

    # Managers and terminal statuses are present.
    statuses = await conn.fetch(
        "SELECT status, COUNT(*) AS n FROM tcs_leads WHERE source = 'demo' GROUP BY status"
    )
    by_status = {row["status"]: row["n"] for row in statuses}
    assert by_status.get("МЕНЕДЖЕР") == 2
    assert by_status.get("КЛИЕНТ") == 2
    assert by_status.get("ОТКАЗ") == 3

    # After-hours share ≈ 40% (12 of 30), checked with the same rule the
    # analytics Phase 3 helper will use (Mon-Fri 09:00-17:00 ET).
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (l.whatsapp_id) m.created_at AS first_at
        FROM tcs_leads l
        JOIN tcs_messages m ON m.whatsapp_id = l.whatsapp_id
        WHERE l.source = 'demo'
        ORDER BY l.whatsapp_id, m.created_at ASC, m.id ASC
        """
    )
    after_hours = sum(
        1
        for row in rows
        if row["first_at"].astimezone(et).weekday() >= 5
        or not 9 <= row["first_at"].astimezone(et).hour < 17
    )
    assert after_hours == 12


async def test_reset_only_deletes_demo_rows(conn):
    await seed.schema_error(conn)
    await seed.run_seed(conn)

    # Foreign (non-demo) rows must survive --reset.
    await conn.execute(
        "INSERT INTO tcs_leads (whatsapp_id, source)"
        " VALUES ($1, 'whatsapp') ON CONFLICT DO NOTHING",
        "tg:999999999",
    )
    await conn.execute(
        "INSERT INTO tcs_messages (whatsapp_id, direction, content) VALUES ($1, 'in', 'real')",
        "tg:999999999",
    )
    await conn.execute(
        "INSERT INTO tcs_events (whatsapp_id, event_type) VALUES ($1, 'stage_entered')",
        "tg:999999999",
    )

    removed = await seed.seed_reset(conn)
    assert removed == 30

    demo_left = await conn.fetchval("SELECT COUNT(*) FROM tcs_leads WHERE source = 'demo'")
    assert demo_left == 0
    demo_msgs = await conn.fetchval(
        "SELECT COUNT(*) FROM tcs_messages"
        " WHERE whatsapp_id IN (SELECT whatsapp_id FROM tcs_leads WHERE source = 'demo')"
    )
    assert demo_msgs == 0

    foreign = await conn.fetchval(
        "SELECT COUNT(*) FROM tcs_leads WHERE whatsapp_id = 'tg:999999999'"
    )
    assert foreign == 1
    foreign_msgs = await conn.fetchval(
        "SELECT COUNT(*) FROM tcs_messages WHERE whatsapp_id = 'tg:999999999'"
    )
    assert foreign_msgs == 1
    foreign_events = await conn.fetchval(
        "SELECT COUNT(*) FROM tcs_events WHERE whatsapp_id = 'tg:999999999'"
    )
    assert foreign_events == 1


async def test_no_truncate_and_demo_marker(conn):
    """Demo rows are tagged with source='demo' (hard rule)."""
    await seed.schema_error(conn)
    await seed.run_seed(conn)
    sources = await conn.fetch(
        "SELECT DISTINCT source FROM tcs_leads WHERE whatsapp_id LIKE 'tg:900%'"
    )
    assert {row["source"] for row in sources} == {"demo"}
    # lead_data carries the demo extras.
    row = await conn.fetchrow("SELECT lead_data FROM tcs_leads WHERE source = 'demo' LIMIT 1")
    data = row["lead_data"] if isinstance(row["lead_data"], dict) else json.loads(row["lead_data"])
    assert set(data) == {"budget_usd", "unit", "pets"}
    # Nothing wrote via TRUNCATE: the transaction-scoped DELETE path is what
    # reset uses (verified above); here we only assert the module never calls it.
    source = Path(seed.__file__).read_text(encoding="utf-8")
    assert "TRUNCATE TABLE" not in source
    # crm_settings access stays valid JSONB (no string "2").
    raw = await conn.fetchval(
        "SELECT value::text FROM crm_settings WHERE key = 'unanswered_after_minutes'"
    )
    assert raw == "2"
    assert await conn.fetchval("SELECT 1") == 1  # connection still usable
