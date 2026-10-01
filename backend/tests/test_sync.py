from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.services.funnel_seed import seed_default_funnel
from backend.app.workers.sync_worker import run_sync_cycle

pytestmark = pytest.mark.usefixtures("db_available")

WA_BASE = "799900002"


def _wa(n: int) -> str:
    return f"{WA_BASE}{n:02d}@c.us"


def _factory(settings):
    engine = create_async_engine(settings.sqlalchemy_url, connect_args=settings.connect_args)
    return engine, async_sessionmaker(bind=engine, expire_on_commit=False)


async def _insert_lead(session, n: int, stage: str = "НОВЫЙ_ЛИД", status: str = "ACTIVE") -> str:
    wa = _wa(n)
    await session.execute(
        text(
            "INSERT INTO knewit_leads"
            " (whatsapp_id, name, current_stage, status, goal, trial_datetime)"
            " VALUES (:wa, :name, :stage, :status, 'test goal', :trial)"
        ),
        {
            "wa": wa,
            "name": f"Sync Test {n}",
            "stage": stage,
            "status": status,
            "trial": datetime(2026, 10, 5, 10, 0, 0) if n == 11 else None,
        },
    )
    return wa


async def _purge(factory, numbers: list[int]) -> None:
    ids = [_wa(n) for n in numbers]
    async with factory() as session:
        contacts = (
            (
                await session.execute(
                    text("SELECT id FROM crm_contacts WHERE whatsapp_id = ANY(:ids)"),
                    {"ids": ids},
                )
            )
            .scalars()
            .all()
        )
        deals: list = []
        for contact_id in contacts:
            deals += (
                (
                    await session.execute(
                        text("SELECT id FROM crm_deals WHERE contact_id = :id"), {"id": contact_id}
                    )
                )
                .scalars()
                .all()
            )
        for deal_id in deals:
            await session.execute(
                text("DELETE FROM crm_deal_stage_history WHERE deal_id = :id"), {"id": deal_id}
            )
            await session.execute(
                text("DELETE FROM crm_activity_log WHERE entity_id = :id"), {"id": deal_id}
            )
        for contact_id in contacts:
            await session.execute(
                text("DELETE FROM crm_activity_log WHERE entity_id = :id"), {"id": contact_id}
            )
            await session.execute(
                text("DELETE FROM crm_deals WHERE contact_id = :id"), {"id": contact_id}
            )
            await session.execute(
                text("DELETE FROM crm_contacts WHERE id = :id"), {"id": contact_id}
            )
        await session.execute(
            text("DELETE FROM crm_conversation_state WHERE whatsapp_id = ANY(:ids)"),
            {"ids": ids},
        )
        await session.execute(
            text("DELETE FROM knewit_events WHERE whatsapp_id = ANY(:ids)"), {"ids": ids}
        )
        await session.execute(
            text("DELETE FROM knewit_leads WHERE whatsapp_id = ANY(:ids)"), {"ids": ids}
        )
        await session.commit()


async def _deal_info(factory, wa: str) -> dict:
    async with factory() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT d.id, d.status, d.stage_locked, d.closed_at, d.trial_at,"
                        " d.custom, s.name AS stage, s.kind, s.bot_stage_key,"
                        " c.name AS contact_name, c.custom AS contact_custom"
                        " FROM crm_deals d JOIN crm_stages s ON s.id = d.stage_id"
                        " JOIN crm_contacts c ON c.id = d.contact_id"
                        " WHERE c.whatsapp_id = :wa"
                        " AND d.deleted_at IS NULL"
                        " ORDER BY d.updated_at DESC LIMIT 1"
                    ),
                    {"wa": wa},
                )
            )
            .mappings()
            .one()
        )
        return dict(row)


async def _counts(factory) -> dict:
    async with factory() as session:
        tables = (
            "crm_contacts",
            "crm_deals",
            "crm_deal_stage_history",
            "crm_conversation_state",
            "crm_activity_log",
        )
        out = {}
        for table in tables:
            out[table] = (await session.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar()
        return out


async def test_backfill_seed_leads(settings):
    engine, factory = _factory(settings)
    try:
        # Forced full scan: deterministic regardless of other suites' markers.
        stats = await run_sync_cycle(factory, force_full=True)
        assert stats is not None
        # Idempotent: seed leads may already be synced by an earlier run.
        assert stats.leads_seen >= 6

        lead1 = await _deal_info(factory, "77010000001@c.us")
        assert lead1["stage"] == "Новый лид"
        assert lead1["bot_stage_key"] == "НОВЫЙ_ЛИД"
        assert lead1["status"] == "open"
        assert lead1["contact_name"] == "Айгерим Тестова"
        assert lead1["contact_custom"]["goal"] == "Шить для себя"

        client = await _deal_info(factory, "77010000005@c.us")
        assert client["status"] == "won"
        assert client["stage"] == "Клиент"
        assert client["closed_at"] is not None

        lost = await _deal_info(factory, "77010000006@c.us")
        assert lost["status"] == "lost"
        assert lost["stage"] == "Отказ"
        assert lost["closed_at"] is not None

        booked = await _deal_info(factory, "77010000002@c.us")
        assert booked["stage"] == "Запись"
        assert booked["trial_at"] is not None

        async with factory() as session:
            states = (
                await session.execute(text("SELECT COUNT(*) FROM crm_conversation_state"))
            ).scalar()
            assert states >= 6
            synced = (
                await session.execute(
                    text("SELECT value FROM crm_settings WHERE key = 'sync_worker.last_synced_at'")
                )
            ).scalar()
            assert synced is not None
    finally:
        await engine.dispose()


async def test_rerun_is_idempotent(settings):
    engine, factory = _factory(settings)
    try:
        first = await run_sync_cycle(factory)
        before = await _counts(factory)
        second = await run_sync_cycle(factory)
        after = await _counts(factory)
        assert first is not None and second is not None
        assert before == after
        assert second.contacts_created == 0
        assert second.deals_created == 0
        assert second.moved == 0
    finally:
        await engine.dispose()


async def test_bot_stage_move_writes_history(settings):
    engine, factory = _factory(settings)
    try:
        async with factory() as session:
            wa = await _insert_lead(session, 11)
            await session.commit()
        try:
            await run_sync_cycle(factory)
            info = await _deal_info(factory, wa)
            assert info["bot_stage_key"] == "НОВЫЙ_ЛИД"

            async with factory() as session:
                await session.execute(
                    text(
                        "UPDATE knewit_leads SET current_stage = 'ЗАПИСЬ',"
                        " previous_stage = 'НОВЫЙ_ЛИД', updated_at = now()"
                        " WHERE whatsapp_id = :wa"
                    ),
                    {"wa": wa},
                )
                await session.commit()

            stats = await run_sync_cycle(factory)
            assert stats.moved == 1
            info = await _deal_info(factory, wa)
            assert info["bot_stage_key"] == "ЗАПИСЬ"
            assert info["trial_at"] is not None

            async with factory() as session:
                history = (
                    (
                        await session.execute(
                            text(
                                "SELECT h.source FROM crm_deal_stage_history h"
                                " JOIN crm_deals d ON d.id = h.deal_id"
                                " JOIN crm_contacts c ON c.id = d.contact_id"
                                " WHERE c.whatsapp_id = :wa ORDER BY h.at"
                            ),
                            {"wa": wa},
                        )
                    )
                    .scalars()
                    .all()
                )
                assert history == ["system", "bot"]
        finally:
            await _purge(factory, [11])
    finally:
        await engine.dispose()


async def test_stage_locked_blocks_move_but_logs(settings):
    engine, factory = _factory(settings)
    try:
        async with factory() as session:
            wa = await _insert_lead(session, 12, stage="КВАЛИФИКАЦИЯ")
            await session.commit()
        try:
            await run_sync_cycle(factory)
            async with factory() as session:
                deal_id = (
                    await session.execute(
                        text(
                            "SELECT d.id FROM crm_deals d"
                            " JOIN crm_contacts c ON c.id = d.contact_id"
                            " WHERE c.whatsapp_id = :wa"
                        ),
                        {"wa": wa},
                    )
                ).scalar_one()
                await session.execute(
                    text("UPDATE crm_deals SET stage_locked = TRUE WHERE id = :id"),
                    {"id": deal_id},
                )
                await session.execute(
                    text(
                        "UPDATE knewit_leads SET current_stage = 'ПРЕЗЕНТАЦИЯ_РЕШЕНИЯ',"
                        " updated_at = now() WHERE whatsapp_id = :wa"
                    ),
                    {"wa": wa},
                )
                await session.commit()

            history_before = (await _counts(factory))["crm_deal_stage_history"]
            stats = await run_sync_cycle(factory)
            assert stats.moved == 0
            assert stats.blocked == 1

            info = await _deal_info(factory, wa)
            assert info["bot_stage_key"] == "КВАЛИФИКАЦИЯ"
            assert (await _counts(factory))["crm_deal_stage_history"] == history_before

            async with factory() as session:
                blocked = (
                    (
                        await session.execute(
                            text(
                                "SELECT action, diff FROM crm_activity_log"
                                " WHERE entity = 'deal' AND entity_id = :id"
                                " ORDER BY created_at DESC LIMIT 1"
                            ),
                            {"id": deal_id},
                        )
                    )
                    .mappings()
                    .one()
                )
                assert blocked["action"] == "bot_stage_blocked"
                assert blocked["diff"]["lead_stage"] == "ПРЕЗЕНТАЦИЯ_РЕШЕНИЯ"
        finally:
            await _purge(factory, [12])
    finally:
        await engine.dispose()


async def test_status_client_and_lost_close_deal(settings):
    engine, factory = _factory(settings)
    try:
        async with factory() as session:
            wa = await _insert_lead(session, 13)
            await session.commit()
        try:
            await run_sync_cycle(factory)
            async with factory() as session:
                await session.execute(
                    text(
                        "UPDATE knewit_leads SET status = 'КЛИЕНТ', updated_at = now()"
                        " WHERE whatsapp_id = :wa"
                    ),
                    {"wa": wa},
                )
                await session.commit()
            await run_sync_cycle(factory)
            info = await _deal_info(factory, wa)
            assert info["status"] == "won"
            assert info["stage"] == "Клиент"
            assert info["closed_at"] is not None

            async with factory() as session:
                await session.execute(
                    text(
                        "UPDATE knewit_leads SET status = 'ОТКАЗ', updated_at = now()"
                        " WHERE whatsapp_id = :wa"
                    ),
                    {"wa": wa},
                )
                await session.commit()
            await run_sync_cycle(factory)
            info = await _deal_info(factory, wa)
            assert info["status"] == "lost"
            assert info["stage"] == "Отказ"
        finally:
            await _purge(factory, [13])
    finally:
        await engine.dispose()


async def test_unknown_stage_falls_back_to_first_open(settings):
    engine, factory = _factory(settings)
    try:
        async with factory() as session:
            wa = await _insert_lead(session, 14, stage="НЕСУЩЕСТВУЮЩИЙ_ЭТАП")
            await session.commit()
        try:
            await run_sync_cycle(factory)
            info = await _deal_info(factory, wa)
            assert info["stage"] == "Новый лид"
            assert info["status"] == "open"
        finally:
            await _purge(factory, [14])
    finally:
        await engine.dispose()


async def test_manager_edits_survive_unchanged_bot_sync(settings):
    """Manual custom keys, contact.name and trial_at survive a sync pass."""

    engine, factory = _factory(settings)
    try:
        async with factory() as session:
            wa = await _insert_lead(session, 21)
            await session.commit()
        try:
            await run_sync_cycle(factory)
            manager_trial = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)
            async with factory() as session:
                await session.execute(
                    text(
                        "UPDATE crm_contacts SET name = 'Manager Edited',"
                        " custom = custom || :patch WHERE whatsapp_id = :wa"
                    ),
                    {"wa": wa, "patch": '{"manager_note": "keep me", "vip": true}'},
                )
                await session.execute(
                    text(
                        "UPDATE crm_deals SET trial_at = :trial,"
                        " custom = custom || :patch WHERE contact_id ="
                        " (SELECT id FROM crm_contacts WHERE whatsapp_id = :wa)"
                    ),
                    {
                        "wa": wa,
                        "trial": manager_trial,
                        "patch": '{"manager_note": "keep me"}',
                    },
                )
                await session.commit()

            await run_sync_cycle(factory)
            info = await _deal_info(factory, wa)
            # Manager values survive an unchanged-bot sync.
            assert info["contact_name"] == "Manager Edited"
            assert info["contact_custom"]["manager_note"] == "keep me"
            assert info["contact_custom"]["vip"] is True
            assert info["custom"]["manager_note"] == "keep me"
            assert info["trial_at"] is not None
            got = info["trial_at"]
            if got.tzinfo is None:
                got = got.replace(tzinfo=UTC)
            assert got == manager_trial
            # Bot-mirrored keys are still present.
            assert info["contact_custom"]["goal"] == "test goal"
        finally:
            await _purge(factory, [21])
    finally:
        await engine.dispose()


async def test_bot_changes_still_apply_but_manual_keys_survive(settings):
    """Bot updates flow through while manual custom keys are preserved."""

    engine, factory = _factory(settings)
    try:
        async with factory() as session:
            wa = await _insert_lead(session, 22)
            await session.commit()
        try:
            await run_sync_cycle(factory)
            async with factory() as session:
                await session.execute(
                    text(
                        "UPDATE crm_contacts SET custom = custom || :patch"
                        " WHERE whatsapp_id = :wa"
                    ),
                    {"wa": wa, "patch": '{"manager_note": "keep me"}'},
                )
                await session.execute(
                    text(
                        "UPDATE crm_deals SET custom = custom || :patch"
                        " WHERE contact_id ="
                        " (SELECT id FROM crm_contacts WHERE whatsapp_id = :wa)"
                    ),
                    {"wa": wa, "patch": '{"manager_note": "keep me"}'},
                )
                await session.commit()

            new_trial = datetime(2026, 12, 2, 12, 0, 0, tzinfo=UTC)
            async with factory() as session:
                await session.execute(
                    text(
                        "UPDATE knewit_leads SET name = 'New Bot Name', goal = 'new goal',"
                        " trial_datetime = :trial, updated_at = now()"
                        " WHERE whatsapp_id = :wa"
                    ),
                    {"wa": wa, "trial": new_trial},
                )
                await session.commit()

            await run_sync_cycle(factory)
            info = await _deal_info(factory, wa)
            # Bot fields updated (manager did not touch the name).
            assert info["contact_name"] == "New Bot Name"
            assert info["contact_custom"]["goal"] == "new goal"
            assert info["trial_at"] is not None
            got = info["trial_at"]
            if got.tzinfo is None:
                got = got.replace(tzinfo=UTC)
            assert got == new_trial
            # Manual keys survived alongside the bot update.
            assert info["contact_custom"]["manager_note"] == "keep me"
            assert info["custom"]["manager_note"] == "keep me"

            # Bot NULL trial must not erase the synced trial.
            async with factory() as session:
                await session.execute(
                    text(
                        "UPDATE knewit_leads SET trial_datetime = NULL, updated_at = now()"
                        " WHERE whatsapp_id = :wa"
                    ),
                    {"wa": wa},
                )
                await session.commit()
            await run_sync_cycle(factory)
            again = await _deal_info(factory, wa)
            got = again["trial_at"]
            if got.tzinfo is None:
                got = got.replace(tzinfo=UTC)
            assert got == new_trial
        finally:
            await _purge(factory, [22])
    finally:
        await engine.dispose()


LOAD_WA_PREFIX = "7999loadtest"


async def _purge_load(factory) -> None:
    pattern = f"{LOAD_WA_PREFIX}%"
    async with factory() as session:
        await session.execute(
            text(
                "DELETE FROM crm_deal_stage_history WHERE deal_id IN"
                " (SELECT d.id FROM crm_deals d JOIN crm_contacts c ON c.id = d.contact_id"
                " WHERE c.whatsapp_id LIKE :pattern)"
            ),
            {"pattern": pattern},
        )
        await session.execute(
            text(
                "DELETE FROM crm_activity_log WHERE entity_id IN"
                " (SELECT d.id FROM crm_deals d JOIN crm_contacts c ON c.id = d.contact_id"
                " WHERE c.whatsapp_id LIKE :pattern)"
            ),
            {"pattern": pattern},
        )
        await session.execute(
            text(
                "DELETE FROM crm_activity_log WHERE entity_id IN"
                " (SELECT id FROM crm_contacts WHERE whatsapp_id LIKE :pattern)"
            ),
            {"pattern": pattern},
        )
        await session.execute(
            text(
                "DELETE FROM crm_deals WHERE contact_id IN"
                " (SELECT id FROM crm_contacts WHERE whatsapp_id LIKE :pattern)"
            ),
            {"pattern": pattern},
        )
        await session.execute(
            text("DELETE FROM crm_contacts WHERE whatsapp_id LIKE :pattern"),
            {"pattern": pattern},
        )
        await session.execute(
            text("DELETE FROM crm_conversation_state WHERE whatsapp_id LIKE :pattern"),
            {"pattern": pattern},
        )
        # Cascades to knewit_messages / knewit_events / knewit_followups.
        await session.execute(
            text("DELETE FROM knewit_leads WHERE whatsapp_id LIKE :pattern"),
            {"pattern": pattern},
        )
        await session.commit()


async def test_load_idle_cycle_under_one_second(settings):
    """3000 leads + 30000 messages: a no-change cycle must take < 1s."""
    engine, factory = _factory(settings)
    try:
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO knewit_leads"
                    " (whatsapp_id, name, current_stage, status, goal, created_at, updated_at)"
                    " SELECT :prefix || lpad(g::text, 5, '0') || '@c.us',"
                    " 'Load ' || g, 'НОВЫЙ_ЛИД', 'ACTIVE', 'load goal',"
                    " now() - interval '1 hour', now() - interval '1 hour'"
                    " FROM generate_series(0, 2999) g"
                    " ON CONFLICT (whatsapp_id) DO NOTHING"
                ),
                {"prefix": LOAD_WA_PREFIX},
            )
            await session.execute(
                text(
                    "INSERT INTO knewit_messages"
                    " (whatsapp_id, direction, message_type, content, created_at)"
                    " SELECT :prefix || lpad((g / 10)::text, 5, '0') || '@c.us',"
                    " 'in', 'chat', 'load msg',"
                    " now() - interval '1 hour' + (g % 10) * interval '1 second'"
                    " FROM generate_series(0, 29999) g"
                ),
                {"prefix": LOAD_WA_PREFIX},
            )
            await session.commit()
        try:
            synced = await run_sync_cycle(factory, force_full=True)
            assert synced is not None
            assert synced.contacts_created >= 3000
            assert synced.deals_created >= 3000
            async with factory() as session:
                pattern = f"{LOAD_WA_PREFIX}%"
                synced_contacts = (
                    await session.execute(
                        text("SELECT COUNT(*) FROM crm_contacts WHERE whatsapp_id LIKE :p"),
                        {"p": pattern},
                    )
                ).scalar()
                synced_deals = (
                    await session.execute(
                        text(
                            "SELECT COUNT(*) FROM crm_deals d JOIN crm_contacts c"
                            " ON c.id = d.contact_id WHERE c.whatsapp_id LIKE :p"
                            " AND d.deleted_at IS NULL"
                        ),
                        {"p": pattern},
                    )
                ).scalar()
                assert synced_contacts == 3000
                assert synced_deals == 3000

            started = time.perf_counter()
            idle = await run_sync_cycle(factory)
            elapsed = time.perf_counter() - started
            assert idle is not None
            assert idle.leads_seen == 0
            assert idle.contacts_created == 0
            assert idle.deals_created == 0
            assert elapsed < 1.0, f"idle cycle took {elapsed:.3f}s"
        finally:
            await _purge_load(factory)
    finally:
        await engine.dispose()


async def test_seed_is_idempotent(tx_session):
    await tx_session.run_sync(seed_default_funnel)
    counts = {}
    for table, expected in (
        ("crm_pipelines", 1),
        ("crm_stages", 16),
        ("crm_lost_reasons", 5),
    ):
        counts[table] = (await tx_session.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar()
        assert counts[table] == expected, (table, counts[table])


async def test_lifespan_starts_worker_when_enabled(settings):
    from asgi_lifespan import LifespanManager

    from backend.app.config import Settings
    from backend.app.main import create_app

    enabled = Settings(
        cookie_secure=False,
        sync_enabled=True,
        sync_interval_seconds=1,
        DATABASE_URL=settings.database_url,
        SECRET_KEY="test-secret-key",
    )
    engine, factory = _factory(settings)
    try:
        async with factory() as session:
            wa = await _insert_lead(session, 15)
            await session.commit()
        try:
            app = create_app(enabled)
            async with LifespanManager(app):
                assert app.state.sync_task is not None
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    async with factory() as session:
                        found = (
                            await session.execute(
                                text("SELECT id FROM crm_contacts WHERE whatsapp_id = :wa"),
                                {"wa": wa},
                            )
                        ).scalar_one_or_none()
                    if found is not None:
                        break
                    await asyncio.sleep(0.2)
                assert found is not None, "worker did not sync the lead in time"
        finally:
            await _purge(factory, [15])
    finally:
        await engine.dispose()
