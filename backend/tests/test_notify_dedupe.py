from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text

from backend.app.services.event_bus import bus
from backend.app.services.notifications import notify
from backend.tests.crm_helpers import admin_csrf, engine_factory, make_manager

pytestmark = pytest.mark.usefixtures("db_available")


async def _user_id(client, token) -> str:
    manager = await make_manager(client, token)
    return manager["user"]["id"]


async def test_notify_publishes_nothing_before_commit(client, settings):
    """Bus events must only fire after the notification is committed."""
    engine, factory = engine_factory(settings)
    try:
        token = await admin_csrf(client, settings)
        user_id = await _user_id(client, token)
        queue = bus.subscribe()
        try:
            async with factory() as session:
                pending = await notify(
                    session,
                    [uuid.UUID(user_id)],
                    "deal_assigned",
                    {"deal_id": "x", "dedupe_key": f"precommit-{uuid.uuid4().hex}"},
                )
                assert queue.empty(), "notify() published before commit"
                await session.rollback()
                assert not pending or queue.empty()
        finally:
            bus.unsubscribe(queue)
    finally:
        await engine.dispose()


async def test_concurrent_notify_dedupes_to_one_row(client, settings):
    """Ten parallel notifies with one key leave exactly one unread row."""
    engine, factory = engine_factory(settings)
    try:
        token = await admin_csrf(client, settings)
        user_id = await _user_id(client, token)
        key = f"race-{uuid.uuid4().hex}"

        async def _one() -> int:
            async with factory() as session:
                pending = await notify(
                    session,
                    [uuid.UUID(user_id)],
                    "task_overdue",
                    {"task_id": "t", "dedupe_key": key},
                )
                await session.commit()
                return len(pending)

        created = await asyncio.gather(*[_one() for _ in range(10)])
        assert sum(created) == 1

        async with factory() as session:
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM crm_notifications"
                        " WHERE user_id = :uid AND type = 'task_overdue'"
                        " AND dedupe_key = :key AND read_at IS NULL"
                    ),
                    {"uid": user_id, "key": key},
                )
            ).scalar()
            assert count == 1
            await session.execute(
                text("DELETE FROM crm_notifications WHERE dedupe_key = :key"), {"key": key}
            )
            await session.commit()
    finally:
        await engine.dispose()
