from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from backend.app.workers.notify_worker import run_notify_cycle
from backend.tests.conftest import csrf_headers, login_admin
from backend.tests.crm_helpers import engine_factory, make_manager

pytestmark = pytest.mark.usefixtures("db_available")

PREFIX = "unans-"


async def _state(factory, wa: str, *, direction: str, paused: bool, at, assigned=None) -> None:
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO crm_conversation_state"
                " (whatsapp_id, bot_paused, last_message_direction, last_message_at, assigned_to)"
                " VALUES (:wa, :paused, :direction, :at, :assigned)"
            ),
            {"wa": wa, "paused": paused, "direction": direction, "at": at, "assigned": assigned},
        )
        await session.commit()


async def _cleanup(factory) -> None:
    async with factory() as session:
        await session.execute(
            text("DELETE FROM crm_notifications WHERE dedupe_key LIKE :p"),
            {"p": f"unanswered:{PREFIX}%"},
        )
        await session.execute(
            text("DELETE FROM crm_conversation_state WHERE whatsapp_id LIKE :p"),
            {"p": PREFIX + "%"},
        )
        await session.commit()


async def test_threshold_setting_is_validated_and_defaults_to_ten(client, settings):
    admin = await login_admin(client, settings)
    headers = csrf_headers(admin["csrf"])
    try:
        current = (await client.get("/api/settings")).json()
        assert 1 <= current["unanswered_after_minutes"] <= 1440
        assert (
            await client.patch(
                "/api/settings", json={"unanswered_after_minutes": 0}, headers=headers
            )
        ).status_code == 422
        changed = await client.patch(
            "/api/settings", json={"unanswered_after_minutes": 15}, headers=headers
        )
        assert changed.status_code == 200
        assert changed.json()["unanswered_after_minutes"] == 15
    finally:
        await client.patch("/api/settings", json={"unanswered_after_minutes": 10}, headers=headers)


async def test_needs_reply_filter_and_row_flag(client, settings):
    engine, factory = engine_factory(settings)
    now = datetime.now(UTC)
    old = now - timedelta(hours=1)
    try:
        await login_admin(client, settings)
        await _state(factory, PREFIX + "open@c.us", direction="in", paused=False, at=old)
        await _state(factory, PREFIX + "paused@c.us", direction="in", paused=True, at=old)
        await _state(factory, PREFIX + "answered@c.us", direction="out", paused=False, at=old)
        await _state(factory, PREFIX + "fresh@c.us", direction="in", paused=False, at=now)

        filtered = (await client.get(f"/api/dialogs?search={PREFIX}&needs_reply=true")).json()[
            "items"
        ]
        assert [d["whatsapp_id"] for d in filtered] == [PREFIX + "open@c.us"]
        assert filtered[0]["needs_reply"] is True

        everything = (await client.get(f"/api/dialogs?search={PREFIX}")).json()["items"]
        flags = {d["whatsapp_id"]: d["needs_reply"] for d in everything}
        assert flags[PREFIX + "fresh@c.us"] is False
        assert flags[PREFIX + "paused@c.us"] is False
        assert flags[PREFIX + "answered@c.us"] is False
    finally:
        await _cleanup(factory)
        await engine.dispose()


async def test_unanswered_notification_once_per_episode(client, settings):
    engine, factory = engine_factory(settings)
    now = datetime.now(UTC)
    wa = PREFIX + "notify@c.us"
    old_wa = PREFIX + "stale@c.us"
    try:
        admin = await login_admin(client, settings)
        manager = await make_manager(client, admin["csrf"])
        manager_id = manager["user"]["id"]
        await _state(
            factory,
            wa,
            direction="in",
            paused=False,
            at=now - timedelta(minutes=30),
            assigned=manager_id,
        )
        await _state(
            factory,
            old_wa,
            direction="in",
            paused=False,
            at=now - timedelta(days=3),
            assigned=manager_id,
        )
        key = f"unanswered:{wa}:"

        async def count_for(prefix: str, user_id: str) -> int:
            async with factory() as session:
                return (
                    await session.execute(
                        text(
                            "SELECT COUNT(*) FROM crm_notifications"
                            " WHERE type = 'unanswered' AND user_id = :u"
                            " AND dedupe_key LIKE :k"
                        ),
                        {"u": user_id, "k": prefix + "%"},
                    )
                ).scalar_one()

        await run_notify_cycle(factory)
        assert await count_for(key, manager_id) == 1
        await run_notify_cycle(factory)
        assert await count_for(key, manager_id) == 1

        async with factory() as session:
            await session.execute(
                text("UPDATE crm_notifications SET read_at = now() WHERE dedupe_key LIKE :k"),
                {"k": key + "%"},
            )
            await session.commit()
        await run_notify_cycle(factory)
        assert await count_for(key, manager_id) == 1

        assert await count_for(f"unanswered:{old_wa}:", manager_id) == 0
    finally:
        await _cleanup(factory)
        await engine.dispose()
