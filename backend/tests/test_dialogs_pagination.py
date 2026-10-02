from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import text

from backend.tests.crm_helpers import admin_csrf, engine_factory

pytestmark = pytest.mark.usefixtures("db_available")

PREFIX = f"perf{uuid.uuid4().hex[:6]}"
COUNT = 20000


async def _seed_bulk(factory) -> None:
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO knewit_leads (whatsapp_id, name, current_stage, status)"
                f" SELECT '{PREFIX}' || g || '@c.us', 'Perf', 'НОВЫЙ_ЛИД', 'ACTIVE'"
                f" FROM generate_series(1, :n) g"
            ),
            {"n": COUNT},
        )
        await session.execute(
            text(
                "INSERT INTO knewit_messages (whatsapp_id, direction, message_type,"
                " content, created_at)"
                f" SELECT '{PREFIX}' || g || '@c.us', 'in', 'chat', 'hello ' || g,"
                " now() - (g || ' seconds')::interval"
                f" FROM generate_series(1, :n) g"
            ),
            {"n": COUNT},
        )
        await session.execute(
            text(
                "INSERT INTO crm_conversation_state (whatsapp_id, unread_count,"
                " last_read_at, last_message_at, last_message_direction,"
                " last_message_preview)"
                f" SELECT '{PREFIX}' || g || '@c.us', 0, now(),"
                " now() - (g || ' seconds')::interval, 'in', 'hello ' || g"
                f" FROM generate_series(1, :n) g"
            ),
            {"n": COUNT},
        )
        # One dialog without any message sorts last (NULLS LAST).
        await session.execute(
            text(
                "INSERT INTO crm_conversation_state (whatsapp_id, unread_count)"
                f" VALUES ('{PREFIX}none@c.us', 0)"
            )
        )
        await session.commit()
    # Explicit VACUUM ANALYZE: without it the autovacuum daemon may fire
    # mid-measurement (20k fresh inserts always cross its threshold) and blow
    # the 200ms budget with background I/O. Manual vacuum also settles stats.
    engine = factory.kw["bind"]
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        for table in ("crm_conversation_state", "knewit_messages", "knewit_leads"):
            await conn.execute(text(f"VACUUM ANALYZE {table}"))


async def _purge_bulk(factory) -> None:
    async with factory() as session:
        await session.execute(
            text("DELETE FROM crm_conversation_state WHERE whatsapp_id LIKE :p"),
            {"p": f"{PREFIX}%"},
        )
        await session.execute(
            text("DELETE FROM knewit_messages WHERE whatsapp_id LIKE :p"),
            {"p": f"{PREFIX}%"},
        )
        await session.execute(
            text("DELETE FROM knewit_leads WHERE whatsapp_id LIKE :p"),
            {"p": f"{PREFIX}%"},
        )
        await session.commit()


async def test_dialogs_list_paginates_in_sql_under_200ms(client, settings):
    engine, factory = engine_factory(settings)
    try:
        await admin_csrf(client, settings)
        await _seed_bulk(factory)
        # Warmup (pool/connection setup is not query work).
        warm = await client.get(f"/api/dialogs?limit=50&offset=0&search={PREFIX}")
        assert warm.status_code == 200

        started = time.perf_counter()
        first = await client.get(f"/api/dialogs?limit=50&offset=0&search={PREFIX}")
        elapsed_first = time.perf_counter() - started
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["total"] == COUNT + 1
        assert len(body["items"]) == 50
        # Newest message first; the message-less dialog sorts last overall.
        assert body["items"][0]["whatsapp_id"] == f"{PREFIX}1@c.us"
        assert body["items"][0]["last_message"]["content"] == "hello 1"

        started = time.perf_counter()
        last_page = await client.get(f"/api/dialogs?limit=50&offset={COUNT}&search={PREFIX}")
        elapsed_last = time.perf_counter() - started
        assert last_page.status_code == 200
        tail = last_page.json()["items"]
        assert tail and tail[-1]["whatsapp_id"] == f"{PREFIX}none@c.us"
        assert tail[-1]["last_message"] is None

        assert elapsed_first < 0.2, f"first page took {elapsed_first:.3f}s"
        assert elapsed_last < 0.2, f"last page took {elapsed_last:.3f}s"
    finally:
        await _purge_bulk(factory)
        await engine.dispose()
