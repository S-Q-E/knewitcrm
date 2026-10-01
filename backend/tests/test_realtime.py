from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient, Timeout
from sqlalchemy import text

from backend.app.routers import stream as stream_router
from backend.app.services.event_bus import EventBus, bus
from backend.app.workers.realtime_poller import RealtimePoller
from backend.tests.conftest import csrf_headers, login, login_admin
from backend.tests.crm_helpers import (
    create_contact,
    create_deal,
    default_pipeline,
    engine_factory,
    make_manager,
    purge_contacts,
    purge_rows,
    run_sync,
)

pytestmark = pytest.mark.usefixtures("db_available")


@pytest.fixture()
def clean_bus():
    bus.reset()
    yield bus
    bus.reset()


@asynccontextmanager
async def live_server(app):
    """Real TCP server (uvicorn) for streaming tests.

    httpx's ASGI transport buffers the whole response body, so infinite
    SSE streams can only be tested over a real socket. Yields (base_url,
    timeout); tests open their own clients (no read timeout: streams stay
    open until explicitly closed).
    """
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started, "uvicorn did not start"
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}", Timeout(connect=10, read=None, write=10, pool=30)
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=20)


def _wa() -> str:
    return f"7999{uuid.uuid4().hex[:8]}@c.us"


async def _insert_lead(factory, wa: str) -> None:
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO knewit_leads (whatsapp_id, name, current_stage, status)"
                " VALUES (:wa, 'Realtime Bot', 'НОВЫЙ_ЛИД', 'ACTIVE')"
            ),
            {"wa": wa},
        )
        await session.commit()


async def _purge_lead(factory, wa: str) -> None:
    from backend.tests.crm_helpers import purge_contacts

    async with factory() as session:
        contacts = (
            (
                await session.execute(
                    text("SELECT id FROM crm_contacts WHERE whatsapp_id = :wa"), {"wa": wa}
                )
            )
            .scalars()
            .all()
        )
        await session.execute(text("DELETE FROM crm_outbox WHERE whatsapp_id = :wa"), {"wa": wa})
        await session.execute(text("DELETE FROM knewit_leads WHERE whatsapp_id = :wa"), {"wa": wa})
        await session.commit()
    await purge_contacts(factory, [str(c) for c in contacts])


class _Stream:
    """One open SSE connection over a real socket."""

    def __init__(self, context, response, iterator):
        self._context = context
        self.response = response
        self.iterator = iterator

    async def aclose(self) -> None:
        await self._context.__aexit__(None, None, None)


async def _open_stream(client: AsyncClient) -> _Stream:
    """Open an SSE stream and consume the connect comment."""
    context = client.stream("GET", "/api/stream")
    response = await context.__aenter__()
    assert response.status_code == 200, response.text
    assert "text/event-stream" in response.headers["content-type"]
    iterator = response.aiter_lines()
    first = await asyncio.wait_for(iterator.__anext__(), timeout=15)
    assert first.startswith(":")
    return _Stream(context, response, iterator)


async def _next_event(iterator, timeout: float = 15) -> dict:
    """Read lines until a full SSE event arrives; return {name, data}."""
    name = ""
    async for line in iterator:
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            return {"name": name, "data": json.loads(line[len("data:") :].strip())}
    raise AssertionError("stream ended without an event")


async def _wait_for_subscribers(count: int, timeout: float = 10) -> None:
    """Disconnect cleanup races the server; wait for it to settle."""
    for _ in range(int(timeout / 0.05)):
        if bus.subscriber_count() == count:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"subscriber count did not settle to {count}")


def test_bus_fanout_and_backpressure():
    local = EventBus(maxsize=2)
    first = local.subscribe()
    second = local.subscribe()
    assert local.subscriber_count() == 2
    assert local.publish("ping", {"n": 1}) == 2
    assert first.get_nowait()["type"] == "ping"
    assert second.get_nowait()["data"] == {"n": 1}
    # A slow consumer never blocks the publisher: oldest is dropped.
    local.publish("a", {})
    local.publish("b", {})
    local.publish("c", {})
    assert first.qsize() == 2
    assert [first.get_nowait()["type"], first.get_nowait()["type"]] == ["b", "c"]
    local.unsubscribe(first)
    local.unsubscribe(second)
    assert local.subscriber_count() == 0
    assert local.publish("ping", {}) == 0


def test_bus_churn_leaves_no_subscribers():
    local = EventBus()
    for _ in range(1000):
        queue = local.subscribe()
        local.publish("ping", {})
        queue.get_nowait()
        local.unsubscribe(queue)
    assert local.subscriber_count() == 0


async def test_poller_publishes_new_rows_once(settings, clean_bus):
    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        await _insert_lead(factory, wa)
        poller = RealtimePoller(factory, clean_bus)
        await poller.start()
        # Rows that already existed at startup are history, not events.
        assert await poller.poll_once() == {"messages": 0, "events": 0}

        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO knewit_messages (whatsapp_id, direction, message_type, content)"
                    " VALUES (:wa, 'in', 'chat', 'hello realtime')"
                ),
                {"wa": wa},
            )
            await session.execute(
                text(
                    "INSERT INTO knewit_events (whatsapp_id, event_type)"
                    " VALUES (:wa, 'stage_entered')"
                ),
                {"wa": wa},
            )
            await session.commit()

        stats = await poller.poll_once()
        assert stats == {"messages": 1, "events": 1}
        # Second poll sees nothing: cursors advanced, no duplicates.
        assert await poller.poll_once() == {"messages": 0, "events": 0}
    finally:
        await _purge_lead(factory, wa)
        await engine.dispose()


async def test_stream_requires_auth(app):
    async with live_server(app) as (base, timeout):
        async with AsyncClient(base_url=base, timeout=timeout) as anonymous:
            response = await anonymous.get("/api/stream")
            assert response.status_code == 401


async def test_stream_broadcasts_pause_to_all_subscribers(app, settings, clean_bus):
    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        async with live_server(app) as (base, timeout):
            async with AsyncClient(base_url=base, timeout=timeout) as client:
                await login_admin(client, settings)
                token = client.cookies.get("crm_csrf")
                assert token
                headers = csrf_headers(token)
                await _insert_lead(factory, wa)
                first = await _open_stream(client)
                second = await _open_stream(client)
                try:
                    paused = await client.post(f"/api/chats/{wa}/bot/pause", headers=headers)
                    assert paused.status_code == 200
                    for stream in (first, second):
                        event = await asyncio.wait_for(_next_event(stream.iterator), timeout=15)
                        assert event["name"] == "bot_paused"
                        assert event["data"] == {"whatsapp_id": wa, "paused": True}
                finally:
                    await first.aclose()
                    await second.aclose()
                await _wait_for_subscribers(0)
    finally:
        await _purge_lead(factory, wa)
        await engine.dispose()


async def test_stream_delivers_notifications_only_to_owner(app, settings, clean_bus):
    engine, factory = engine_factory(settings)
    try:
        async with live_server(app) as (base, timeout):
            async with (
                AsyncClient(base_url=base, timeout=timeout) as admin_client,
                AsyncClient(base_url=base, timeout=timeout) as mgr_client,
            ):
                await login_admin(admin_client, settings)
                admin_token = admin_client.cookies.get("crm_csrf")
                assert admin_token
                manager = await make_manager(admin_client, admin_token)
                await login(mgr_client, manager["email"], manager["password"])
                mgr_stream = await _open_stream(mgr_client)
                admin_stream = await _open_stream(admin_client)
                try:
                    async with factory() as session:
                        from backend.app.services.notifications import notify

                        await notify(
                            session,
                            [manager["user"]["id"]],
                            "deal_assigned",
                            {"deal_id": "x", "dedupe_key": "realtime-test-1"},
                        )
                        await session.commit()
                    event = await asyncio.wait_for(_next_event(mgr_stream.iterator), timeout=15)
                    assert event["name"] == "notification"
                    assert event["data"]["user_id"] == manager["user"]["id"]
                    # The admin's stream must stay silent: the event is not theirs.
                    with pytest.raises(asyncio.TimeoutError):
                        await asyncio.wait_for(_next_event(admin_stream.iterator), timeout=2)
                finally:
                    await mgr_stream.aclose()
                    await admin_stream.aclose()
                await _wait_for_subscribers(0)
    finally:
        async with factory() as session:
            await session.execute(text("DELETE FROM crm_notifications"))
            await session.commit()
        await engine.dispose()


async def test_stream_heartbeat(app, settings, monkeypatch, clean_bus):
    monkeypatch.setattr(stream_router, "HEARTBEAT_SECONDS", 0.1)
    engine, factory = engine_factory(settings)
    try:
        async with live_server(app) as (base, timeout):
            async with AsyncClient(base_url=base, timeout=timeout) as client:
                await login_admin(client, settings)
                stream = await _open_stream(client)
                try:
                    async for line in stream.iterator:
                        if line.startswith(": heartbeat"):
                            break
                    else:
                        raise AssertionError("no heartbeat received")
                finally:
                    await stream.aclose()
        await _wait_for_subscribers(0)
    finally:
        await engine.dispose()


async def test_sync_move_publishes_deal_moved(settings, clean_bus):
    from backend.app.services.event_bus import bus as global_bus

    engine, factory = engine_factory(settings)
    wa = _wa()
    seen: list[dict] = []
    queue = global_bus.subscribe()
    try:
        await _insert_lead(factory, wa)
        await run_sync(factory)
        async with factory() as session:
            await session.execute(
                text(
                    "UPDATE knewit_leads SET current_stage = 'ЗАПИСЬ', updated_at = now()"
                    " WHERE whatsapp_id = :wa"
                ),
                {"wa": wa},
            )
            await session.commit()
        await run_sync(factory)
        while True:
            try:
                seen.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        moved = [e for e in seen if e["type"] == "deal_moved"]
        assert len(moved) == 1
        assert moved[0]["data"]["source"] == "bot"
        assert moved[0]["data"]["deal_id"]
    finally:
        global_bus.unsubscribe(queue)
        await _purge_lead(factory, wa)
        await engine.dispose()


async def test_manager_move_publishes_deal_moved(client, settings, clean_bus):
    engine, factory = engine_factory(settings)
    token = (await login_admin(client, settings))["csrf"]
    pipeline = await default_pipeline(client)
    contact = await create_contact(client, token)
    deal = await create_deal(client, token, contact["id"], pipeline)
    try:
        queue = clean_bus.subscribe()
        try:
            stages = pipeline["stages"]
            other = next(s for s in stages if s["id"] != deal["stage_id"] and s["kind"] == "open")
            moved = await client.post(
                f"/api/deals/{deal['id']}/move",
                json={"stage_id": other["id"]},
                headers=csrf_headers(token),
            )
            assert moved.status_code == 200, moved.text
            events = []
            while True:
                try:
                    events.append(queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            moved_events = [e for e in events if e["type"] == "deal_moved"]
            assert len(moved_events) == 1
            assert moved_events[0]["data"]["deal_id"] == deal["id"]
            assert moved_events[0]["data"]["source"] == "manager"
        finally:
            clean_bus.unsubscribe(queue)
    finally:
        await purge_contacts(factory, [contact["id"]])
        await engine.dispose()


async def test_task_create_publishes_task_created(client, settings, clean_bus):
    engine, factory = engine_factory(settings)
    try:
        admin = await login_admin(client, settings)
        payload = {"title": "Realtime task check", "type": "message"}
        queue = clean_bus.subscribe()
        try:
            created = await client.post(
                "/api/tasks", json=payload, headers=csrf_headers(admin["csrf"])
            )
            assert created.status_code == 201, created.text
            try:
                events = []
                while True:
                    try:
                        events.append(queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                task_events = [e for e in events if e["type"] == "task_created"]
                assert len(task_events) == 1
                assert task_events[0]["data"]["task_id"] == created.json()["id"]
            finally:
                await purge_rows(factory, "crm_tasks", [created.json()["id"]])
        finally:
            clean_bus.unsubscribe(queue)
    finally:
        await engine.dispose()


def test_deal_visibility_filter_for_restricted_manager():
    from backend.app.auth_deps import CurrentUser
    from backend.app.routers.stream import event_visible

    admin = CurrentUser(id=uuid.uuid4(), email="a@x.com", name="A", role="admin")
    manager = CurrentUser(id=uuid.uuid4(), email="m@x.com", name="M", role="manager")
    other = uuid.uuid4()
    assert event_visible({"type": "deal_moved", "data": {"owner_id": None}}, manager, True)
    assert event_visible(
        {"type": "deal_moved", "data": {"owner_id": str(manager.id)}}, manager, True
    )
    assert not event_visible(
        {"type": "deal_moved", "data": {"owner_id": str(other)}}, manager, True
    )
    assert event_visible({"type": "deal_moved", "data": {"owner_id": str(other)}}, manager, False)
    assert event_visible({"type": "deal_moved", "data": {"owner_id": str(other)}}, admin, True)
    assert event_visible(
        {"type": "notification", "data": {"user_id": str(manager.id)}}, manager, True
    )
    assert not event_visible(
        {"type": "notification", "data": {"user_id": str(other)}}, manager, True
    )
    assert event_visible({"type": "new_message", "data": {}}, manager, True)


async def test_whatsapp_visibility_lookup(client, settings):
    """Bot events resolve visibility through the linked contact owner."""
    from backend.app.auth_deps import CurrentUser
    from backend.app.routers.stream import whatsapp_visible

    engine, factory = engine_factory(settings)
    wa_owned = _wa()
    wa_free = _wa()
    try:
        admin = await login_admin(client, settings)
        stranger = await make_manager(client, admin["csrf"])
        owned = await create_contact(
            client,
            admin["csrf"],
            whatsapp_id=wa_owned,
            owner_id=stranger["user"]["id"],
            name="Owned Lead",
        )
        manager = CurrentUser(id=uuid.uuid4(), email="m@x.com", name="M", role="manager")
        try:
            async with factory() as session:
                cache: dict[str, bool] = {}
                assert await whatsapp_visible(session, cache, wa_owned, manager, True) is False
                assert await whatsapp_visible(session, cache, wa_free, manager, True) is True
                assert await whatsapp_visible(session, cache, wa_owned, manager, False) is True
                admin_user = CurrentUser(id=uuid.uuid4(), email="a@x.com", name="A", role="admin")
                assert await whatsapp_visible(session, cache, wa_owned, admin_user, True) is True
        finally:
            await purge_contacts(factory, [owned["id"]])
    finally:
        await engine.dispose()


async def test_stream_hides_foreign_bot_events_when_scoped(app, settings, clean_bus):
    engine, factory = engine_factory(settings)
    wa_foreign = _wa()
    wa_free = _wa()
    try:
        async with live_server(app) as (base, timeout):
            async with (
                AsyncClient(base_url=base, timeout=timeout) as admin_client,
                AsyncClient(base_url=base, timeout=timeout) as mgr_client,
            ):
                await login_admin(admin_client, settings)
                admin_token = admin_client.cookies.get("crm_csrf")
                assert admin_token
                stranger = await make_manager(admin_client, admin_token)
                manager = await make_manager(admin_client, admin_token)
                await login(mgr_client, manager["email"], manager["password"])
                await _insert_lead(factory, wa_foreign)
                await _insert_lead(factory, wa_free)
                foreign = await create_contact(
                    admin_client,
                    admin_token,
                    whatsapp_id=wa_foreign,
                    owner_id=stranger["user"]["id"],
                    name="Foreign Lead",
                )
                async with factory() as session:
                    await session.execute(
                        text(
                            "INSERT INTO crm_settings (key, value) VALUES"
                            " ('restrict_managers_to_own', 'true')"
                            " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
                        )
                    )
                    await session.commit()
                try:

                    async def _expect_silence(kind: str, payload: dict) -> None:
                        # A silence check cancels the pending read, which may
                        # break resuming on the same connection, so every
                        # check gets a fresh stream.
                        probe = await _open_stream(mgr_client)
                        try:
                            bus.publish(kind, payload)
                            with pytest.raises(asyncio.TimeoutError):
                                await asyncio.wait_for(_next_event(probe.iterator), timeout=2)
                        finally:
                            await probe.aclose()

                    async def _expect_delivery(kind: str, payload: dict) -> dict:
                        probe = await _open_stream(mgr_client)
                        try:
                            bus.publish(kind, payload)
                            return await asyncio.wait_for(_next_event(probe.iterator), timeout=15)
                        finally:
                            await probe.aclose()

                    foreign_message = {
                        "message_id": 1,
                        "whatsapp_id": wa_foreign,
                        "direction": "in",
                        "message_type": "chat",
                    }
                    free_message = {
                        "message_id": 2,
                        "whatsapp_id": wa_free,
                        "direction": "in",
                        "message_type": "chat",
                    }
                    foreign_event = {
                        "event_id": 1,
                        "whatsapp_id": wa_foreign,
                        "event_type": "stage_entered",
                    }
                    free_event = {
                        "event_id": 2,
                        "whatsapp_id": wa_free,
                        "event_type": "stage_entered",
                    }
                    await _expect_silence("new_message", foreign_message)
                    event = await _expect_delivery("new_message", free_message)
                    assert event["name"] == "new_message"
                    assert event["data"]["whatsapp_id"] == wa_free
                    await _expect_silence("bot_event", foreign_event)
                    event = await _expect_delivery("bot_event", free_event)
                    assert event["name"] == "bot_event"
                    assert event["data"]["whatsapp_id"] == wa_free
                    await _wait_for_subscribers(0)
                finally:
                    async with factory() as session:
                        await session.execute(
                            text("DELETE FROM crm_settings WHERE key = 'restrict_managers_to_own'")
                        )
                        await session.commit()
                await purge_contacts(factory, [foreign["id"]])
    finally:
        await _purge_lead(factory, wa_foreign)
        await _purge_lead(factory, wa_free)
        await engine.dispose()
