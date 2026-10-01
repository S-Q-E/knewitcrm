from __future__ import annotations

import asyncio
import uuid

import pytest

from backend.app.services.normalize import (
    contact_keys,
    normalize_email,
    normalize_phone,
    normalize_whatsapp,
)
from backend.tests.conftest import csrf_headers
from backend.tests.crm_helpers import (
    admin_csrf,
    create_contact,
    create_deal,
    default_pipeline,
    engine_factory,
    purge_contacts,
    purge_rows,
)

pytestmark = pytest.mark.usefixtures("db_available")


def _wa() -> str:
    return f"7999{uuid.uuid4().hex[:8]}@c.us"


def test_normalize_phone_cases() -> None:
    assert normalize_phone("+7 (701) 000-11-22") == "77010001122"
    assert normalize_phone("8 701 000 11 22") == "77010001122"
    assert normalize_phone("77010001122@c.us") == "77010001122"
    assert normalize_phone(None) == ""
    assert normalize_whatsapp("79991234567@c.us") == "79991234567"
    assert normalize_whatsapp("79991234567@lid") == "79991234567"
    assert normalize_email("  AiG@Example.COM ") == "aig@example.com"
    keys = contact_keys("+7 (701) 000-11-22", None, "A@B.cC")
    assert keys == {"phone": "77010001122", "email": "a@b.cc"}
    assert contact_keys("123", None, "") == {"phone": None, "email": None}


async def test_duplicates_and_merge(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        first = await create_contact(
            client, token, name="Dupe One", phone="+7 (701) 111-22-33", whatsapp_id=_wa()
        )
        second = await create_contact(
            client, token, name="Dupe Two", phone="8 701 111 22 33", email="dupe@example.com"
        )
        contact_ids += [first["id"], second["id"]]
        # email duplicate pair
        third = await create_contact(client, token, name="Mail One", email="Same@Example.com")
        fourth = await create_contact(client, token, name="Mail Two", email="same@example.com")
        contact_ids += [third["id"], fourth["id"]]

        dup = await client.get("/api/contacts/duplicates")
        assert dup.status_code == 200, dup.text
        groups = dup.json()["groups"]
        phone_group = next(g for g in groups if g["kind"] == "phone")
        assert {first["id"], second["id"]} <= set(phone_group["contact_ids"])
        mail_group = next(g for g in groups if g["kind"] == "email")
        assert {third["id"], fourth["id"]} <= set(mail_group["contact_ids"])

        # attach a deal + note + task to the loser, then merge loser -> winner
        pipeline = await default_pipeline(client)
        deal = await create_deal(client, token, second["id"], pipeline)
        note = (
            await client.post(
                "/api/notes",
                json={"contact_id": second["id"], "body": "loser note"},
                headers=csrf_headers(token),
            )
        ).json()
        task = (
            await client.post(
                "/api/tasks",
                json={"contact_id": second["id"], "title": "loser task"},
                headers=csrf_headers(token),
            )
        ).json()
        merged = await client.post(
            "/api/contacts/merge",
            json={"winner_id": first["id"], "loser_id": second["id"]},
            headers=csrf_headers(token),
        )
        assert merged.status_code == 200, merged.text
        assert merged.json()["id"] == first["id"]
        # loser is soft-deleted
        assert (await client.get(f"/api/contacts/{second['id']}")).status_code == 404
        # deal moved to winner
        winner_deals = await client.get(f"/api/contacts/{first['id']}/deals")
        assert any(d["id"] == deal["id"] for d in winner_deals.json()["items"])
        # activity log has merge entry
        from sqlalchemy import text

        async with factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT diff FROM crm_activity_log WHERE entity='contact'"
                        " AND entity_id=:id AND action='contact_merged'"
                    ),
                    {"id": first["id"]},
                )
            ).mappings().one_or_none()
        assert row is not None
        await purge_rows(factory, "crm_notes", [note["id"]])
        await purge_rows(factory, "crm_tasks", [task["id"]])
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_contacts_bulk_tags_owner_delete(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        first = await create_contact(client, token, whatsapp_id=_wa())
        second = await create_contact(client, token, whatsapp_id=_wa())
        contact_ids += [first["id"], second["id"]]
        tag = (
            await client.post(
                "/api/tags", json={"name": f"b-{uuid.uuid4().hex[:8]}"}, headers=csrf_headers(token)
            )
        ).json()
        bulk = await client.post(
            "/api/contacts/bulk",
            json={"ids": [first["id"], second["id"]], "add_tag_id": tag["id"]},
            headers=csrf_headers(token),
        )
        assert bulk.status_code == 200, bulk.text
        assert bulk.json() == {"updated": 2}
        fetched = await client.get(f"/api/contacts/{first['id']}")
        assert any(t["id"] == tag["id"] for t in fetched.json()["tags"])
        await purge_rows(factory, "crm_tags", [tag["id"]])
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_export_contacts_and_deals(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        created = await create_contact(client, token, name="Export Me", whatsapp_id=_wa())
        contact_ids.append(created["id"])
        csv_resp = await client.get("/api/contacts/export?format=csv&search=Export%20Me")
        assert csv_resp.status_code == 200, csv_resp.text
        assert csv_resp.headers["content-type"].startswith("text/csv")
        body = csv_resp.content.decode("utf-8-sig")
        assert "Export Me" in body
        assert body.splitlines()[0].startswith("id,")
        xlsx_resp = await client.get("/api/contacts/export?format=xlsx&search=Export%20Me")
        assert xlsx_resp.status_code == 200
        assert xlsx_resp.content[:2] == b"PK"
        deals_csv = await client.get("/api/deals/export?format=csv")
        assert deals_csv.status_code == 200
        deals_xlsx = await client.get("/api/deals/export?format=xlsx")
        assert deals_xlsx.status_code == 200 and deals_xlsx.content[:2] == b"PK"
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_import_preview_and_background_job(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        csv_text = (
            "full_name,phone_number,email,src\n"
            "Иван,+77011112233,ivan@example.com,import\n"
            "Плохой,123,not-an-email,import\n"
            ",,,import\n"
        )
        mapping = {"full_name": "name", "phone_number": "phone", "email": "email", "src": "source"}
        import json as _json

        preview = await client.post(
            "/api/contacts/import/preview",
            files={"file": ("contacts.csv", csv_text.encode(), "text/csv")},
            data={"mapping": _json.dumps(mapping)},
            headers=csrf_headers(token),
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["total"] == 3
        assert body["valid"] == 1 and body["invalid"] == 2
        assert body["preview"][0]["name"] == "Иван"

        job_resp = await client.post(
            "/api/contacts/import",
            files={"file": ("contacts.csv", csv_text.encode(), "text/csv")},
            data={"mapping": _json.dumps(mapping)},
            headers=csrf_headers(token),
        )
        assert job_resp.status_code == 201, job_resp.text
        job_id = job_resp.json()["id"]
        for _ in range(100):
            status = await client.get(f"/api/contacts/import/{job_id}")
            assert status.status_code == 200
            if status.json()["status"] == "done":
                break
            await asyncio.sleep(0.05)
        final = (await client.get(f"/api/contacts/import/{job_id}")).json()
        assert final["status"] == "done"
        assert final["ok_count"] == 1 and final["error_count"] == 2
        assert len(final["errors"]) == 2
        found = await client.get("/api/contacts?search=ivan@example.com")
        assert any("Иван" in (i["name"] or "") for i in found.json()["items"])
        for item in found.json()["items"]:
            if item["email"] == "ivan@example.com":
                contact_ids.append(item["id"])
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_trash_lists_deleted(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        created = await create_contact(client, token, name="Trash Me", whatsapp_id=_wa())
        contact_ids.append(created["id"])
        await client.delete(f"/api/contacts/{created['id']}", headers=csrf_headers(token))
        trash = await client.get("/api/trash?kind=contact")
        assert trash.status_code == 200, trash.text
        assert any(i["id"] == created["id"] for i in trash.json()["items"])
        restored = await client.post(
            f"/api/contacts/{created['id']}/restore", headers=csrf_headers(token)
        )
        assert restored.status_code == 200
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_contact_timeline_and_deals(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        created = await create_contact(client, token, name="Timeline Guy", whatsapp_id=_wa())
        contact_ids.append(created["id"])
        pipeline = await default_pipeline(client)
        deal = await create_deal(client, token, created["id"], pipeline)
        await client.post(
            "/api/notes",
            json={"contact_id": created["id"], "body": "hello note"},
            headers=csrf_headers(token),
        )
        timeline = await client.get(f"/api/contacts/{created['id']}/timeline")
        assert timeline.status_code == 200, timeline.text
        kinds = {i["kind"] for i in timeline.json()["items"]}
        assert "note" in kinds and "stage" in kinds
        deals = await client.get(f"/api/contacts/{created['id']}/deals")
        assert any(d["id"] == deal["id"] for d in deals.json()["items"])
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()
