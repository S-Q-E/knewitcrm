from __future__ import annotations

import uuid

import pytest

from backend.tests.conftest import csrf_headers
from backend.tests.crm_helpers import (
    ManagerSession,
    admin_csrf,
    assert_logged,
    create_contact,
    engine_factory,
    make_manager,
    purge_contacts,
    purge_rows,
)

pytestmark = pytest.mark.usefixtures("db_available")


def _wa() -> str:
    return f"7999{uuid.uuid4().hex[:8]}@c.us"


async def test_notes_crud_and_pin(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        contact = await create_contact(client, token, whatsapp_id=_wa())
        contact_ids.append(contact["id"])

        orphan = await client.post(
            "/api/notes", json={"body": "nowhere"}, headers=csrf_headers(token)
        )
        assert orphan.status_code == 422

        created = await client.post(
            "/api/notes",
            json={"contact_id": contact["id"], "body": "First note", "pinned": True},
            headers=csrf_headers(token),
        )
        assert created.status_code == 201
        note_id = created.json()["id"]
        await assert_logged(factory, "note", note_id, "note_created")

        listed = await client.get(f"/api/notes?contact_id={contact['id']}")
        assert listed.json()["total"] == 1

        unpinned = await client.patch(
            f"/api/notes/{note_id}",
            json={"pinned": False},
            headers=csrf_headers(token),
        )
        assert unpinned.json()["pinned"] is False

        gone = await client.delete(f"/api/notes/{note_id}", headers=csrf_headers(token))
        assert gone.json() == {"ok": True}
        assert (await client.get(f"/api/notes/{note_id}")).status_code == 404
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_note_delete_permissions(client, settings, app):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        contact = await create_contact(client, token, whatsapp_id=_wa())
        contact_ids.append(contact["id"])
        first = await make_manager(client, token)
        second = await make_manager(client, token)

        async with ManagerSession(app, first["email"], first["password"]) as mgr:
            assert mgr.client is not None
            created = await mgr.client.post(
                "/api/notes",
                json={"contact_id": contact["id"], "body": "Mine"},
                headers=mgr.headers(),
            )
            note_id = created.json()["id"]

        async with ManagerSession(app, second["email"], second["password"]) as mgr2:
            assert mgr2.client is not None
            forbidden = await mgr2.client.delete(f"/api/notes/{note_id}", headers=mgr2.headers())
            assert forbidden.status_code == 403

        admin_delete = await client.delete(f"/api/notes/{note_id}", headers=csrf_headers(token))
        assert admin_delete.json() == {"ok": True}
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_tags_crud_and_permissions(client, settings, app):
    engine, factory = engine_factory(settings)
    tag_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        tag = (
            await client.post(
                "/api/tags",
                json={"name": f"g-{uuid.uuid4().hex[:8]}", "color": "#fff"},
                headers=csrf_headers(token),
            )
        ).json()
        tag_ids.append(tag["id"])

        dup = await client.post(
            "/api/tags", json={"name": tag["name"]}, headers=csrf_headers(token)
        )
        assert dup.status_code == 409

        manager = await make_manager(client, token)
        async with ManagerSession(app, manager["email"], manager["password"]) as mgr:
            assert mgr.client is not None
            own = await mgr.client.post(
                "/api/tags",
                json={"name": f"m-{uuid.uuid4().hex[:8]}"},
                headers=mgr.headers(),
            )
            assert own.status_code == 201
            tag_ids.append(own.json()["id"])
            forbidden = await mgr.client.delete(f"/api/tags/{tag['id']}", headers=mgr.headers())
            assert forbidden.status_code == 403

        gone = await client.delete(f"/api/tags/{tag['id']}", headers=csrf_headers(token))
        assert gone.json()["ok"] is True
        tag_ids.remove(tag["id"])
    finally:
        await purge_rows(factory, "crm_tags", tag_ids)
        await engine.dispose()


async def test_custom_fields_admin_only_and_validation(client, settings, app):
    engine, factory = engine_factory(settings)
    field_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        bad_key = await client.post(
            "/api/custom-fields",
            json={"entity": "deal", "key": "Bad Key!", "label": "Bad", "type": "text"},
            headers=csrf_headers(token),
        )
        assert bad_key.status_code == 422

        bad_options = await client.post(
            "/api/custom-fields",
            json={"entity": "deal", "key": "channel", "label": "Channel", "type": "select"},
            headers=csrf_headers(token),
        )
        assert bad_options.status_code == 422

        field = (
            await client.post(
                "/api/custom-fields",
                json={
                    "entity": "deal",
                    "key": "channel",
                    "label": "Channel",
                    "type": "select",
                    "options": ["online", "offline"],
                },
                headers=csrf_headers(token),
            )
        ).json()
        field_ids.append(field["id"])
        await assert_logged(factory, "custom_field", field["id"], "custom_field_created")

        manager = await make_manager(client, token)
        async with ManagerSession(app, manager["email"], manager["password"]) as mgr:
            assert mgr.client is not None
            forbidden = await mgr.client.post(
                "/api/custom-fields",
                json={"entity": "deal", "key": "x", "label": "X", "type": "text"},
                headers=mgr.headers(),
            )
            assert forbidden.status_code == 403
            visible = await mgr.client.get("/api/custom-fields?entity=deal")
            assert any(f["key"] == "channel" for f in visible.json()["items"])
    finally:
        await purge_rows(factory, "crm_custom_fields", field_ids)
        await engine.dispose()


async def test_lost_reasons_crud_and_in_use(client, settings, app):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    reason_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        reason = (
            await client.post(
                "/api/lost-reasons",
                json={"name": f"lr-{uuid.uuid4().hex[:8]}"},
                headers=csrf_headers(token),
            )
        ).json()
        reason_ids.append(reason["id"])

        manager = await make_manager(client, token)
        async with ManagerSession(app, manager["email"], manager["password"]) as mgr:
            assert mgr.client is not None
            forbidden = await mgr.client.post(
                "/api/lost-reasons", json={"name": "Nope"}, headers=mgr.headers()
            )
            assert forbidden.status_code == 403
            visible = await mgr.client.get("/api/lost-reasons")
            assert any(r["id"] == reason["id"] for r in visible.json()["items"])

        from backend.tests.crm_helpers import create_deal, default_pipeline

        pipeline = await default_pipeline(client)
        contact = await create_contact(client, token, whatsapp_id=_wa())
        contact_ids.append(contact["id"])
        deal = await create_deal(client, token, contact["id"], pipeline)
        closed = await client.patch(
            f"/api/deals/{deal['id']}",
            json={"status": "lost", "lost_reason_id": reason["id"]},
            headers=csrf_headers(token),
        )
        assert closed.status_code == 200

        in_use = await client.delete(
            f"/api/lost-reasons/{reason['id']}", headers=csrf_headers(token)
        )
        assert in_use.status_code == 409
    finally:
        await purge_contacts(factory, contact_ids)
        await purge_rows(factory, "crm_lost_reasons", reason_ids)
        await engine.dispose()
