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
)

pytestmark = pytest.mark.usefixtures("db_available")


def _wa() -> str:
    return f"7999{uuid.uuid4().hex[:8]}@c.us"


async def test_tasks_crud_and_lifecycle(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        contact = await create_contact(client, token, whatsapp_id=_wa())
        contact_ids.append(contact["id"])

        orphan = await client.post(
            "/api/tasks", json={"title": "nowhere"}, headers=csrf_headers(token)
        )
        assert orphan.status_code == 422

        created = await client.post(
            "/api/tasks",
            json={
                "contact_id": contact["id"],
                "title": "Call back",
                "type": "call",
                "due_at": "2026-12-01T10:00:00Z",
            },
            headers=csrf_headers(token),
        )
        assert created.status_code == 201
        task_id = created.json()["id"]
        assert created.json()["done_at"] is None
        await assert_logged(factory, "task", task_id, "task_created")

        open_list = await client.get(f"/api/tasks?contact_id={contact['id']}&open_only=true")
        assert open_list.json()["total"] == 1

        done = await client.post(f"/api/tasks/{task_id}/done", headers=csrf_headers(token))
        assert done.json()["done_at"] is not None
        assert (await client.get(f"/api/tasks?contact_id={contact['id']}&open_only=true")).json()[
            "total"
        ] == 0

        undone = await client.post(f"/api/tasks/{task_id}/undone", headers=csrf_headers(token))
        assert undone.json()["done_at"] is None

        bad_assignee = await client.patch(
            f"/api/tasks/{task_id}",
            json={"assignee_id": "00000000-0000-0000-0000-000000000000"},
            headers=csrf_headers(token),
        )
        assert bad_assignee.status_code == 422

        gone = await client.delete(f"/api/tasks/{task_id}", headers=csrf_headers(token))
        assert gone.json() == {"ok": True}
        assert (await client.get(f"/api/tasks/{task_id}")).status_code == 404
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_task_overdue_and_delete_permissions(client, settings, app):
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
                "/api/tasks",
                json={
                    "contact_id": contact["id"],
                    "title": "Old",
                    "due_at": "2020-01-01T00:00:00Z",
                },
                headers=mgr.headers(),
            )
            task_id = created.json()["id"]

        overdue = await client.get("/api/tasks?overdue=true")
        assert any(t["id"] == task_id for t in overdue.json()["items"])

        async with ManagerSession(app, second["email"], second["password"]) as mgr2:
            assert mgr2.client is not None
            forbidden = await mgr2.client.delete(f"/api/tasks/{task_id}", headers=mgr2.headers())
            assert forbidden.status_code == 403

        admin_delete = await client.delete(f"/api/tasks/{task_id}", headers=csrf_headers(token))
        assert admin_delete.json() == {"ok": True}
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()
