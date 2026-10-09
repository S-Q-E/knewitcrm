from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from backend.app.services.event_bus import bus
from backend.tests.conftest import csrf_headers
from backend.tests.crm_helpers import (
    ManagerSession,
    admin_csrf,
    create_contact,
    create_deal,
    default_pipeline,
    engine_factory,
    make_manager,
    purge_contacts,
)
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


async def test_visibility_matrix_exports_notes_and_import_status(client, settings, app):
    engine, factory = engine_factory(settings)
    secret = f"ScopeExp{uuid.uuid4().hex[:8]}"
    job_id: str | None = None
    try:
        token = await admin_csrf(client, settings)
        owner = await make_manager(client, token)
        stranger = await make_manager(client, token)
        own_contact = await create_contact(
            client, token, name=f"{secret} own", owner_id=owner["user"]["id"]
        )
        await create_contact(client, token, name=f"{secret} free")
        pipe = await default_pipeline(client)
        own_deal = await create_deal(
            client,
            token,
            own_contact["id"],
            pipe,
            title=f"{secret} own deal",
            owner_id=owner["user"]["id"],
        )
        gone_contact = await create_contact(client, token, name=f"{secret} gone")
        await create_deal(client, token, gone_contact["id"], pipe, title=f"{secret} gone deal")
        note = await client.post(
            "/api/notes",
            json={"contact_id": own_contact["id"], "body": f"{secret} note"},
            headers=csrf_headers(token),
        )
        assert note.status_code == 201, note.text
        note_id = note.json()["id"]
        deal_note = await client.post(
            "/api/notes",
            json={"deal_id": own_deal["id"], "body": f"{secret} deal note"},
            headers=csrf_headers(token),
        )
        assert deal_note.status_code == 201, deal_note.text
        deal_note_id = deal_note.json()["id"]
        deleted = await client.delete(
            f"/api/contacts/{gone_contact['id']}", headers=csrf_headers(token)
        )
        assert deleted.status_code == 200, deleted.text
        csv_bytes = f"name\n{secret} imported\n".encode()
        imported = await client.post(
            "/api/contacts/import",
            files={"file": ("c.csv", csv_bytes, "text/csv")},
            data={"mapping": '{"name":"name"}'},
            headers=csrf_headers(token),
        )
        assert imported.status_code == 201, imported.text
        job_id = imported.json()["id"]
        await _set_restrict(factory, True)
        try:
            async with ManagerSession(app, stranger["email"], stranger["password"]) as mgr:
                assert mgr.client is not None
                contacts_csv = (
                    await mgr.client.get("/api/contacts/export", params={"search": secret})
                ).text
                assert f"{secret} free" in contacts_csv
                assert f"{secret} own" not in contacts_csv
                deals_csv = (
                    await mgr.client.get("/api/deals/export", params={"search": secret})
                ).text
                assert f"{secret} own deal" not in deals_csv

                listed = await mgr.client.get(
                    "/api/notes", params={"contact_id": own_contact["id"]}
                )
                assert listed.status_code == 200
                assert listed.json()["total"] == 0
                listed = await mgr.client.get("/api/notes", params={"deal_id": own_deal["id"]})
                assert listed.json()["total"] == 0
                assert (await mgr.client.get(f"/api/notes/{note_id}")).status_code == 404
                edited = await mgr.client.patch(
                    f"/api/notes/{deal_note_id}", json={"body": "чужая"}, headers=mgr.headers()
                )
                assert edited.status_code == 404
                created = await mgr.client.post(
                    "/api/notes",
                    json={"contact_id": own_contact["id"], "body": "в чужой контакт"},
                    headers=mgr.headers(),
                )
                assert created.status_code == 422, created.text
                assert (await mgr.client.get(f"/api/contacts/import/{job_id}")).status_code == 404

            async with ManagerSession(app, owner["email"], owner["password"]) as own:
                assert own.client is not None
                own_csv = (
                    await own.client.get("/api/contacts/export", params={"search": secret})
                ).text
                assert f"{secret} own" in own_csv
                assert (await own.client.get(f"/api/notes/{note_id}")).status_code == 200
                listed = await own.client.get("/api/notes", params={"deal_id": own_deal["id"]})
                assert listed.json()["total"] == 1
                assert (await own.client.get(f"/api/contacts/import/{job_id}")).status_code == 404

            admin_csv = (await client.get("/api/contacts/export", params={"search": secret})).text
            assert f"{secret} own" in admin_csv and f"{secret} free" in admin_csv
            admin_deals = (await client.get("/api/deals/export", params={"search": secret})).text
            assert f"{secret} own deal" in admin_deals
            assert f"{secret} gone deal" not in admin_deals
            assert (await client.get(f"/api/notes/{note_id}")).status_code == 200
            assert (await client.get(f"/api/contacts/import/{job_id}")).status_code == 200
        finally:
            await _set_restrict(factory, False)
    finally:
        await _purge_scope_rows(factory, secret, job_id)
        await engine.dispose()


async def _contact_ids_by_name(factory, secret: str) -> list[str]:
    async with factory() as session:
        rows = (
            await session.execute(
                text("SELECT id FROM crm_contacts WHERE name LIKE :p"), {"p": f"{secret}%"}
            )
        ).scalars()
        return [str(r) for r in rows]


async def _purge_scope_rows(factory, secret: str, job_id: str | None) -> None:
    async with factory() as session:
        if job_id is not None:
            await session.execute(
                text("DELETE FROM crm_activity_log WHERE entity_id = :id"), {"id": job_id}
            )
            await session.execute(text("DELETE FROM crm_imports WHERE id = :id"), {"id": job_id})
        await session.commit()
    await purge_contacts(factory, await _contact_ids_by_name(factory, secret))
