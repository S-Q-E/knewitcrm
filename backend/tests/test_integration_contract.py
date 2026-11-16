"""Contract between CRM and the n8n-owned tcs_* tables.

The checks run on the test database built from tests/fixtures/tcs_schema.sql,
which mirrors the production schema (see docs/db_schema.md). They fail when CRM
code starts touching a table or column that production does not have, or when
the fixture drifts away from what CRM depends on.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import text

from backend.tests.crm_helpers import engine_factory

pytestmark = pytest.mark.usefixtures("db_available")

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# Columns CRM reads or writes (queries in services/, routers/, workers/).
KNEWIT_CONTRACT: dict[str, set[str]] = {
    "tcs_leads": {
        "id",
        "whatsapp_id",
        "name",
        "status",
        "current_stage",
        "previous_stage",
        "direction",
        "goal",
        "experience_level",
        "preferred_format",
        "preferred_time",
        "trial_datetime",
        "last_objection",
        "created_at",
        "updated_at",
        "last_message_at",
    },
    "tcs_messages": {
        "id",
        "whatsapp_id",
        "direction",
        "message_type",
        "content",
        "stage_at_moment",
        "tokens_used",
        "response_time_ms",
        "created_at",
    },
    "tcs_events": {
        "id",
        "whatsapp_id",
        "event_type",
        "from_stage",
        "to_stage",
        "payload",
        "created_at",
    },
}

# Types CRM relies on: crm_outbox.tcs_message_id is BigInteger, and the
# realtime poller compares ids as integers.
KEY_TYPES = {
    ("tcs_messages", "id"): "bigint",
    ("tcs_events", "id"): "bigint",
    ("tcs_leads", "id"): "integer",
}

_SQL_TARGET = re.compile(r"\b(?:FROM|INTO|UPDATE|JOIN)\s+(tcs_[a-z_]+)", re.IGNORECASE)


def _code_tcs_tables() -> set[str]:
    tables: set[str] = set()
    for path in APP_DIR.rglob("*.py"):
        tables.update(m.group(1).lower() for m in _SQL_TARGET.finditer(path.read_text("utf-8")))
    return tables


async def _fetch(settings, sql: str, params: dict | None = None) -> list:
    engine, factory = engine_factory(settings)
    try:
        async with factory() as session:
            return list((await session.execute(text(sql), params or {})).all())
    finally:
        await engine.dispose()


def test_code_uses_only_contracted_tables():
    used = _code_tcs_tables()
    assert used, "no tcs_* references found: the scan is broken"
    unknown = used - set(KNEWIT_CONTRACT)
    assert not unknown, f"CRM code references tcs_* tables outside the contract: {unknown}"


async def test_contracted_columns_exist_in_test_schema(settings):
    rows = await _fetch(
        settings,
        "SELECT table_name, column_name, data_type FROM information_schema.columns"
        " WHERE table_schema = 'public' AND table_name LIKE 'tcs\\_%'",
    )
    actual: dict[str, set[str]] = {}
    types: dict[tuple[str, str], str] = {}
    for table, column, data_type in rows:
        actual.setdefault(table, set()).add(column)
        types[(table, column)] = data_type

    missing = {
        table: sorted(columns - actual.get(table, set()))
        for table, columns in KNEWIT_CONTRACT.items()
        if columns - actual.get(table, set())
    }
    assert not missing, f"tcs_* columns CRM depends on are missing: {missing}"

    wrong = {
        key: (types.get(key), expected)
        for key, expected in KEY_TYPES.items()
        if not (types.get(key) or "").startswith(expected)
    }
    assert not wrong, f"tcs_* key column types drifted: {wrong}"


async def test_whatsapp_id_is_unique_for_leads(settings):
    rows = await _fetch(
        settings,
        "SELECT kcu.column_name FROM information_schema.table_constraints tc"
        " JOIN information_schema.key_column_usage kcu"
        " ON kcu.constraint_name = tc.constraint_name"
        " AND kcu.table_schema = tc.table_schema"
        " WHERE tc.table_schema = 'public' AND tc.table_name = 'tcs_leads'"
        " AND tc.constraint_type = 'UNIQUE'",
    )
    assert ("whatsapp_id",) in rows


async def test_tcs_tables_have_no_foreign_keys(settings):
    # Production has no FKs between tcs_* tables (rows match by whatsapp_id);
    # test cleanup relies on explicit deletes because of this.
    rows = await _fetch(
        settings,
        "SELECT conrelid::regclass::text FROM pg_constraint"
        " WHERE contype = 'f' AND conrelid::regclass::text LIKE 'tcs\\_%'",
    )
    assert rows == []
