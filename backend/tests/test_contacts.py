from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

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


async def test_contact_crud_and_search(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        created = await create_contact(
            client,
            token,
            whatsapp_id=_wa(),
            name="Айгерим Поиск",
            phone="+7 (701) 000-11-22",
            email="aigerim@example.com",
        )
        contact_ids.append(created["id"])

        fetched = await client.get(f"/api/contacts/{created['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["phone"] == "+7 (701) 000-11-22"

        by_name = await client.get("/api/contacts?search=айгерим поиск")
        assert any(i["id"] == created["id"] for i in by_name.json()["items"])
        by_digits = await client.get("/api/contacts?search=7010001122")
        assert any(i["id"] == created["id"] for i in by_digits.json()["items"])
        by_wa = await client.get(f"/api/contacts?search={created['whatsapp_id'][:8]}")
        assert any(i["id"] == created["id"] for i in by_wa.json()["items"])

        patched = await client.patch(
            f"/api/contacts/{created['id']}",
            json={"name": "Айгерим Обнова"},
            headers=csrf_headers(token),
        )
        assert patched.status_code == 200
        assert patched.json()["name"] == "Айгерим Обнова"
        await assert_logged(factory, "contact", created["id"], "contact_updated")
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_contact_filters_and_pagination(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    tag_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        tag = (
            await client.post(
                "/api/tags",
                json={"name": f"t-{uuid.uuid4().hex[:8]}"},
                headers=csrf_headers(token),
            )
        ).json()
        tag_ids.append(tag["id"])
        first = await create_contact(client, token, source="bot", whatsapp_id=_wa())
        second = await create_contact(client, token, source="manual", whatsapp_id=_wa())
        contact_ids += [first["id"], second["id"]]
        tagged = await client.put(
            f"/api/contacts/{first['id']}/tags",
            json={"tag_ids": [tag["id"]]},
            headers=csrf_headers(token),
        )
        assert tagged.status_code == 200

        by_tag = await client.get(f"/api/contacts?tag={tag['id']}")
        ids = [i["id"] for i in by_tag.json()["items"]]
        assert first["id"] in ids and second["id"] not in ids

        by_source = await client.get("/api/contacts?source=manual")
        assert all(i["source"] == "manual" for i in by_source.json()["items"])

        paged = await client.get("/api/contacts?limit=1&offset=0")
        body = paged.json()
        assert len(body["items"]) == 1 and body["total"] >= 2

        by_custom = await client.get("/api/contacts?custom=nosuchkey:1")
        assert by_custom.json()["total"] == 0
    finally:
        await purge_contacts(factory, contact_ids)
        await purge_rows(factory, "crm_tags", tag_ids)
        await engine.dispose()


async def test_contact_custom_validation(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    field_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        key = f"age_{uuid.uuid4().hex[:6]}"
        field = (
            await client.post(
                "/api/custom-fields",
                json={
                    "entity": "contact",
                    "key": key,
                    "label": "Age",
                    "type": "number",
                    "required": True,
                },
                headers=csrf_headers(token),
            )
        ).json()
        field_ids.append(field["id"])

        missing = await client.post(
            "/api/contacts",
            json={"name": "No Age", "custom": {}},
            headers=csrf_headers(token),
        )
        assert missing.status_code == 422

        wrong_type = await client.post(
            "/api/contacts",
            json={"name": "Bad Age", "custom": {key: "old"}},
            headers=csrf_headers(token),
        )
        assert wrong_type.status_code == 422

        ok = await create_contact(client, token, custom={key: 33, "bot_extra": "kept"})
        contact_ids.append(ok["id"])
        assert ok["custom"][key] == 33
        assert ok["custom"]["bot_extra"] == "kept"
    finally:
        await purge_contacts(factory, contact_ids)
        await purge_rows(factory, "crm_custom_fields", field_ids)
        await engine.dispose()


async def test_contact_soft_hard_delete_and_restore(client, settings, app):
    engine, factory = engine_factory(settings)
    try:
        token = await admin_csrf(client, settings)
        created = await create_contact(client, token, whatsapp_id=_wa())
        contact_id = created["id"]

        manager = await make_manager(client, token)
        async with ManagerSession(app, manager["email"], manager["password"]) as mgr:
            assert mgr.client is not None
            hard_forbidden = await mgr.client.delete(
                f"/api/contacts/{contact_id}?hard=true", headers=mgr.headers()
            )
            assert hard_forbidden.status_code == 403

        soft = await client.delete(f"/api/contacts/{contact_id}", headers=csrf_headers(token))
        assert soft.json() == {"ok": True, "hard": False}
        assert (await client.get(f"/api/contacts/{contact_id}")).status_code == 404
        listed = await client.get("/api/contacts?search=Test")
        assert all(i["id"] != contact_id for i in listed.json()["items"])

        restored = await client.post(
            f"/api/contacts/{contact_id}/restore", headers=csrf_headers(token)
        )
        assert restored.status_code == 200

        hard = await client.delete(
            f"/api/contacts/{contact_id}?hard=true", headers=csrf_headers(token)
        )
        assert hard.json() == {"ok": True, "hard": True}
        assert (await client.get(f"/api/contacts/{contact_id}")).status_code == 404
    finally:
        await engine.dispose()


async def test_contact_visibility_scope(client, settings, app):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        owner = await make_manager(client, token)
        stranger = await make_manager(client, token)
        owned = await create_contact(client, token, owner_id=owner["user"]["id"], whatsapp_id=_wa())
        free = await create_contact(client, token, whatsapp_id=_wa())
        contact_ids += [owned["id"], free["id"]]

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
            async with ManagerSession(app, stranger["email"], stranger["password"]) as mgr:
                assert mgr.client is not None
                listed = await mgr.client.get("/api/contacts")
                ids = [i["id"] for i in listed.json()["items"]]
                assert owned["id"] not in ids
                assert free["id"] in ids
                assert (await mgr.client.get(f"/api/contacts/{owned['id']}")).status_code == 404

            async with ManagerSession(app, owner["email"], owner["password"]) as mgr2:
                assert mgr2.client is not None
                assert (await mgr2.client.get(f"/api/contacts/{owned['id']}")).status_code == 200
        finally:
            async with factory() as session:
                await session.execute(
                    text("DELETE FROM crm_settings WHERE key = 'restrict_managers_to_own'")
                )
                await session.commit()
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_contact_errors(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        wa = _wa()
        created = await create_contact(client, token, whatsapp_id=wa)
        contact_ids.append(created["id"])
        dup = await client.post(
            "/api/contacts",
            json={"name": "Dup", "whatsapp_id": wa},
            headers=csrf_headers(token),
        )
        assert dup.status_code == 409

        bad_owner = await client.post(
            "/api/contacts",
            json={"name": "X", "owner_id": "00000000-0000-0000-0000-000000000000"},
            headers=csrf_headers(token),
        )
        assert bad_owner.status_code == 422

        unknown_tag = await client.put(
            f"/api/contacts/{created['id']}/tags",
            json={"tag_ids": ["00000000-0000-0000-0000-000000000000"]},
            headers=csrf_headers(token),
        )
        assert unknown_tag.status_code == 422
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()
