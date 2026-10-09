from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from backend.app.workers.notify_worker import run_notify_cycle
from backend.tests.conftest import csrf_headers, login_admin
from backend.tests.crm_helpers import engine_factory, make_manager

pytestmark = pytest.mark.usefixtures("db_available")

PREFIX = "pal-"


async def _state(factory, wa: str, *, paused: bool, at) -> None:
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO crm_conversation_state (whatsapp_id, bot_paused, paused_at)"
                " VALUES (:wa, :paused, :at)"
            ),
            {"wa": wa, "paused": paused, "at": at},
        )
        await session.commit()


async def _cleanup(factory) -> None:
    async with factory() as session:
        await session.execute(
            text("DELETE FROM crm_notifications WHERE dedupe_key LIKE :p"),
            {"p": f"paused:{PREFIX}%"},
        )
        await session.execute(
            text("DELETE FROM crm_conversation_state WHERE whatsapp_id LIKE :p"),
            {"p": PREFIX + "%"},
        )
        await session.commit()


async def _count(factory, user_id: str, wa: str) -> int:
    async with factory() as session:
        return (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM crm_notifications"
                    " WHERE type = 'bot_paused_long' AND user_id = :u AND dedupe_key LIKE :k"
                ),
                {"u": user_id, "k": f"paused:{wa}:%"},
            )
        ).scalar_one()


async def test_threshold_setting_is_validated_and_defaults_to_six(client, settings):
    admin = await login_admin(client, settings)
    headers = csrf_headers(admin["csrf"])
    try:
        current = (await client.get("/api/settings")).json()
        assert 1 <= current["paused_alert_hours"] <= 50
        for bad in (0, 51):
            response = await client.patch(
                "/api/settings", json={"paused_alert_hours": bad}, headers=headers
            )
            assert response.status_code == 422
        changed = await client.patch(
            "/api/settings", json={"paused_alert_hours": 50}, headers=headers
        )
        assert changed.status_code == 200
        assert changed.json()["paused_alert_hours"] == 50
    finally:
        await client.patch("/api/settings", json={"paused_alert_hours": 6}, headers=headers)


async def test_long_pause_notifies_all_active_users_once_per_episode(client, settings):
    engine, factory = engine_factory(settings)
    now = datetime.now(UTC)
    long_wa = PREFIX + "long@c.us"
    fresh_wa = PREFIX + "fresh@c.us"
    resumed_wa = PREFIX + "resumed@c.us"
    try:
        admin = await login_admin(client, settings)
        headers = csrf_headers(admin["csrf"])
        await client.patch("/api/settings", json={"paused_alert_hours": 6}, headers=headers)
        manager = await make_manager(client, admin["csrf"])
        manager_id = manager["user"]["id"]
        async with factory() as session:
            admin_id = str(
                (
                    await session.execute(
                        text("SELECT id FROM crm_users WHERE email = :e"),
                        {"e": settings.admin_email.lower()},
                    )
                ).scalar_one()
            )
        await _state(factory, long_wa, paused=True, at=now - timedelta(hours=7))
        await _state(factory, fresh_wa, paused=True, at=now - timedelta(hours=1))
        await _state(factory, resumed_wa, paused=False, at=now - timedelta(hours=9))

        await run_notify_cycle(factory)
        assert await _count(factory, manager_id, long_wa) == 1
        assert await _count(factory, admin_id, long_wa) == 1
        assert await _count(factory, manager_id, fresh_wa) == 0
        assert await _count(factory, manager_id, resumed_wa) == 0

        await run_notify_cycle(factory)
        assert await _count(factory, manager_id, long_wa) == 1

        async with factory() as session:
            await session.execute(
                text("UPDATE crm_notifications SET read_at = now() WHERE dedupe_key LIKE :k"),
                {"k": f"paused:{long_wa}:%"},
            )
            await session.commit()
        await run_notify_cycle(factory)
        assert await _count(factory, manager_id, long_wa) == 1

        async with factory() as session:
            await session.execute(
                text("UPDATE crm_conversation_state SET paused_at = :at WHERE whatsapp_id = :wa"),
                {"at": now - timedelta(hours=8), "wa": long_wa},
            )
            await session.commit()
        await run_notify_cycle(factory)
        assert await _count(factory, manager_id, long_wa) == 2
    finally:
        await client.patch("/api/settings", json={"paused_alert_hours": 6}, headers=headers)
        await _cleanup(factory)
        await engine.dispose()
