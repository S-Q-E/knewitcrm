from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from backend.app.services.event_bus import bus
from backend.tests.crm_helpers import admin_csrf, engine_factory, make_manager, purge_contacts
from backend.tests.test_realtime import (
    _next_event,
    _open_stream,
    _wait_for_subscribers,
    live_server,
)

pytestmark = pytest.mark.usefixtures("db_available")


@pytest.fixture()
def clean_bus():
    bus.reset()
    yield bus
    bus.reset()


def _wa() -> str:
    return f"7999{uuid.uuid4().hex[:8]}@c.us"


async def _insert_lead(factory, wa: str) -> None:
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO knewit_leads (whatsapp_id, name, current_stage, status)"
                " VALUES (:wa, 'Scope Bot', 'НОВЫЙ_ЛИД', 'ACTIVE')"
            ),
            {"wa": wa},
        )
        await session.execute(
            text(
                "INSERT INTO knewit_messages (whatsapp_id, direction, message_type, content)"
                " VALUES (:wa, 'in', 'chat', 'hi')"
            ),
            {"wa": wa},
        )
        await session.commit()


async def _purge(factory, was: list[str], contact_ids: list[str]) -> None:
    async with factory() as session:
        await session.execute(
            text("DELETE FROM crm_conversation_state WHERE whatsapp_id = ANY(:ids)"),
            {"ids": was},
        )
        await session.execute(
            text("DELETE FROM crm_outbox WHERE whatsapp_id = ANY(:ids)"), {"ids": was}
        )
        await session.execute(
            text("DELETE FROM knewit_messages WHERE whatsapp_id = ANY(:ids)"), {"ids": was}
        )
        await session.execute(
            text("DELETE FROM knewit_events WHERE whatsapp_id = ANY(:ids)"), {"ids": was}
        )
        await session.execute(
            text("DELETE FROM knewit_leads WHERE whatsapp_id = ANY(:ids)"), {"ids": was}
        )
        await session.commit()
    await purge_contacts(factory, contact_ids)


async def _contact_ids(factory, was: list[str]) -> list[str]:
    async with factory() as session:
        rows = (
            await session.execute(
                text("SELECT id FROM crm_contacts WHERE whatsapp_id = ANY(:ids)"), {"ids": was}
            )
        ).scalars()
        return [str(r) for r in rows]


async def _set_restrict(factory, enabled: bool) -> None:
    async with factory() as session:
        if enabled:
            await session.execute(
                text(
                    "INSERT INTO crm_settings (key, value) VALUES"
                    " ('restrict_managers_to_own', 'true')"
                    " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
                )
            )
        else:
            await session.execute(
                text("DELETE FROM crm_settings WHERE key = 'restrict_managers_to_own'")
            )
        await session.commit()


async def _setup_matrix(client, factory, token, owner_id: str) -> tuple[str, str]:
    """Lead A owned by owner_id (deal owner), lead B free. Returns (wa_own, wa_free)."""
    from backend.tests.crm_helpers import run_sync

    wa_own, wa_free = _wa(), _wa()
    await _insert_lead(factory, wa_own)
    await _insert_lead(factory, wa_free)
    await run_sync(factory)
    async with factory() as session:
        contacts = (
            await session.execute(
                text("SELECT id, whatsapp_id FROM crm_contacts WHERE whatsapp_id = ANY(:ids)"),
                {"ids": [wa_own, wa_free]},
            )
        ).mappings()
        by_wa = {row["whatsapp_id"]: row["id"] for row in contacts}
        await session.execute(
            text("UPDATE crm_contacts SET owner_id = :owner WHERE id = :id"),
            {"owner": owner_id, "id": by_wa[wa_own]},
        )
        await session.execute(
            text(
                "UPDATE crm_deals SET owner_id = :owner WHERE contact_id = :id",
                # noqa: E501
            ),
            {"owner": owner_id, "id": by_wa[wa_own]},
        )
        await session.commit()
    return wa_own, wa_free


async def test_visibility_matrix_dialogs_and_chats(client, settings, app):
    from backend.tests.crm_helpers import ManagerSession

    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    was: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        owner = await make_manager(client, token)
        stranger = await make_manager(client, token)
        wa_own, wa_free = await _setup_matrix(client, factory, token, owner["user"]["id"])
        was = [wa_own, wa_free]
        contact_ids = await _contact_ids(factory, was)
        await _set_restrict(factory, True)
        try:
            async with ManagerSession(app, stranger["email"], stranger["password"]) as mgr:
                assert mgr.client is not None
                listed = await mgr.client.get("/api/dialogs?limit=100")
                assert listed.status_code == 200
                seen = {d["whatsapp_id"] for d in listed.json()["items"]}
                assert wa_free in seen and wa_own not in seen

                assert (await mgr.client.get(f"/api/dialogs/{wa_own}/messages")).status_code == 404
                assert (await mgr.client.get(f"/api/dialogs/{wa_free}/messages")).status_code == 200
                assert (
                    await mgr.client.post(
                        f"/api/chats/{wa_own}/messages",
                        json={"body": "чужой"},
                        headers=mgr.headers(),
                    )
                ).status_code == 404
                assert (
                    await mgr.client.post(
                        f"/api/chats/{wa_free}/messages",
                        json={"body": "свободный"},
                        headers=mgr.headers(),
                    )
                ).status_code == 202
            async with ManagerSession(app, owner["email"], owner["password"]) as mgr2:
                assert mgr2.client is not None
                listed = await mgr2.client.get("/api/dialogs?limit=100")
                seen = {d["whatsapp_id"] for d in listed.json()["items"]}
                assert wa_own in seen and wa_free in seen
                assert (await mgr2.client.get(f"/api/dialogs/{wa_own}/messages")).status_code == 200
            listed = await client.get("/api/dialogs?limit=100")
            seen = {d["whatsapp_id"] for d in listed.json()["items"]}
            assert wa_own in seen and wa_free in seen
        finally:
            await _set_restrict(factory, False)
    finally:
        await _purge(factory, was, contact_ids)
        await engine.dispose()


async def test_visibility_matrix_sse(app, settings, clean_bus):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    was: list[str] = []
    try:
        async with live_server(app) as (base, timeout):
            async with (
                AsyncClient(base_url=base, timeout=timeout) as admin_client,
                AsyncClient(base_url=base, timeout=timeout) as mgr_client,
            ):
                from backend.tests.conftest import login, login_admin

                await login_admin(admin_client, settings)
                admin_token = admin_client.cookies.get("crm_csrf")
                assert admin_token
                owner = await make_manager(admin_client, admin_token)
                stranger = await make_manager(admin_client, admin_token)
                await login(mgr_client, stranger["email"], stranger["password"])
                wa_own, wa_free = await _setup_matrix(
                    admin_client, factory, admin_token, owner["user"]["id"]
                )
                was = [wa_own, wa_free]
                contact_ids = await _contact_ids(factory, was)
                await _set_restrict(factory, True)
                try:

                    async def _silence(kind: str, wa: str) -> None:
                        probe = await _open_stream(mgr_client)
                        try:
                            bus.publish(kind, {"whatsapp_id": wa})
                            with pytest.raises(asyncio.TimeoutError):
                                await asyncio.wait_for(_next_event(probe.iterator), timeout=2)
                        finally:
                            await probe.aclose()

                    async def _delivery(kind: str, wa: str) -> None:
                        probe = await _open_stream(mgr_client)
                        try:
                            bus.publish(kind, {"whatsapp_id": wa})
                            event = await asyncio.wait_for(_next_event(probe.iterator), timeout=15)
                            assert event["name"] == kind
                            assert event["data"]["whatsapp_id"] == wa
                        finally:
                            await probe.aclose()

                    kinds = ("new_message", "bot_event", "outbox_status", "bot_paused")
                    for kind in kinds:
                        await _silence(kind, wa_own)
                    for kind in kinds:
                        await _delivery(kind, wa_free)
                    # Admin bypasses the scope.
                    admin_probe = await _open_stream(admin_client)
                    try:
                        bus.publish("outbox_status", {"whatsapp_id": wa_own})
                        event = await asyncio.wait_for(
                            _next_event(admin_probe.iterator), timeout=15
                        )
                        assert event["name"] == "outbox_status"
                    finally:
                        await admin_probe.aclose()
                    await _wait_for_subscribers(0)
                finally:
                    await _set_restrict(factory, False)
    finally:
        await _purge(factory, was, contact_ids)
        await engine.dispose()
