from __future__ import annotations

import asyncio
import time
from datetime import datetime

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
        stats = await run_sync_cycle(factory)
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
                        " previous_stage = 'НОВЫЙ_ЛИД' WHERE whatsapp_id = :wa"
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
                        "UPDATE knewit_leads SET current_stage = 'ПРЕЗЕНТАЦИЯ_РЕШЕНИЯ'"
                        " WHERE whatsapp_id = :wa"
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
                    text("UPDATE knewit_leads SET status = 'КЛИЕНТ' WHERE whatsapp_id = :wa"),
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
                    text("UPDATE knewit_leads SET status = 'ОТКАЗ' WHERE whatsapp_id = :wa"),
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
