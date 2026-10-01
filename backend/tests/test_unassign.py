from __future__ import annotations

import uuid

import pytest

from backend.tests.conftest import csrf_headers
from backend.tests.crm_helpers import (
    admin_csrf,
    create_contact,
    create_deal,
    default_pipeline,
    engine_factory,
    make_manager,
    purge_contacts,
    purge_rows,
)

pytestmark = pytest.mark.usefixtures("db_available")


def _wa() -> str:
    return f"7999{uuid.uuid4().hex[:8]}@c.us"


async def _create_task(client, token, **overrides) -> dict:
    payload = {"title": f"Task {uuid.uuid4().hex[:8]}", **overrides}
    response = await client.post("/api/tasks", json=payload, headers=csrf_headers(token))
    assert response.status_code == 201, response.text
    return response.json()


async def test_deal_patch_unassign_owner(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        owner = await make_manager(client, token)
        contact = await create_contact(
            client, token, whatsapp_id=_wa(), owner_id=owner["user"]["id"]
        )
        contact_ids.append(contact["id"])
        pipeline = await default_pipeline(client)
        deal = await create_deal(
            client, token, contact["id"], pipeline, owner_id=owner["user"]["id"]
        )
        try:
            # Missing field keeps the owner.
            kept = await client.patch(
                f"/api/deals/{deal['id']}",
                json={"title": "Still owned"},
                headers=csrf_headers(token),
            )
            assert kept.status_code == 200, kept.text
            assert kept.json()["owner_id"] == owner["user"]["id"]
            # Explicit null clears the owner.
            cleared = await client.patch(
                f"/api/deals/{deal['id']}",
                json={"owner_id": None},
                headers=csrf_headers(token),
            )
            assert cleared.status_code == 200, cleared.text
            assert cleared.json()["owner_id"] is None
        finally:
            await purge_rows(factory, "crm_deals", [deal["id"]])
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_contact_patch_unassign_owner(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        owner = await make_manager(client, token)
        contact = await create_contact(
            client, token, whatsapp_id=_wa(), owner_id=owner["user"]["id"]
        )
        contact_ids.append(contact["id"])

        kept = await client.patch(
            f"/api/contacts/{contact['id']}",
            json={"name": "Still owned"},
            headers=csrf_headers(token),
        )
        assert kept.status_code == 200, kept.text
        assert kept.json()["owner_id"] == owner["user"]["id"]

        cleared = await client.patch(
            f"/api/contacts/{contact['id']}",
            json={"owner_id": None},
            headers=csrf_headers(token),
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["owner_id"] is None
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_task_patch_unassign_assignee(client, settings):
    engine, factory = engine_factory(settings)
    task_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        owner = await make_manager(client, token)
        task = await _create_task(client, token, assignee_id=owner["user"]["id"])
        task_ids.append(task["id"])

        kept = await client.patch(
            f"/api/tasks/{task['id']}",
            json={"title": "Still assigned"},
            headers=csrf_headers(token),
        )
        assert kept.status_code == 200, kept.text
        assert kept.json()["assignee_id"] == owner["user"]["id"]

        cleared = await client.patch(
            f"/api/tasks/{task['id']}",
            json={"assignee_id": None},
            headers=csrf_headers(token),
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["assignee_id"] is None
    finally:
        await purge_rows(factory, "crm_tasks", task_ids)
        await engine.dispose()


async def test_bulk_unassign_owner_flag(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    deal_ids: list[str] = []
    task_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        owner = await make_manager(client, token)
        first = await create_contact(client, token, whatsapp_id=_wa(), owner_id=owner["user"]["id"])
        second = await create_contact(
            client, token, whatsapp_id=_wa(), owner_id=owner["user"]["id"]
        )
        contact_ids += [first["id"], second["id"]]
        pipeline = await default_pipeline(client)
        deal = await create_deal(client, token, first["id"], pipeline, owner_id=owner["user"]["id"])
        deal_ids.append(deal["id"])
        task = await _create_task(client, token, assignee_id=owner["user"]["id"])
        task_ids.append(task["id"])

        bulk_deals = await client.post(
            "/api/deals/bulk",
            json={"ids": [deal["id"]], "unassign_owner": True},
            headers=csrf_headers(token),
        )
        assert bulk_deals.status_code == 200, bulk_deals.text
        assert (await client.get(f"/api/deals/{deal['id']}")).json()["owner_id"] is None

        bulk_contacts = await client.post(
            "/api/contacts/bulk",
            json={"ids": [first["id"], second["id"]], "unassign_owner": True},
            headers=csrf_headers(token),
        )
        assert bulk_contacts.status_code == 200, bulk_contacts.text
        for cid in (first["id"], second["id"]):
            assert (await client.get(f"/api/contacts/{cid}")).json()["owner_id"] is None

        bulk_tasks = await client.post(
            "/api/tasks/bulk",
            json={"ids": [task["id"]], "unassign_owner": True},
            headers=csrf_headers(token),
        )
        assert bulk_tasks.status_code == 200, bulk_tasks.text
        assert (await client.get(f"/api/tasks/{task['id']}")).json()["assignee_id"] is None
    finally:
        await purge_rows(factory, "crm_tasks", task_ids)
        await purge_rows(factory, "crm_deals", deal_ids)
        await purge_contacts(factory, contact_ids)
        await engine.dispose()
