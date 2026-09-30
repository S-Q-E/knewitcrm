from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

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

pytestmark = pytest.mark.usefixtures("db_available")


def _wa() -> str:
    return f"7999{uuid.uuid4().hex[:8]}@c.us"


async def _set_assignment(factory, mode: str) -> None:
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO crm_settings (key, value) VALUES"
                " ('deal_assignment', CAST(:value AS jsonb))"
                " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            ),
            {"value": json.dumps({"mode": mode, "last_index": -1})},
        )
        await session.commit()


async def _clear_assignment(factory) -> None:
    async with factory() as session:
        await session.execute(text("DELETE FROM crm_settings WHERE key = 'deal_assignment'"))
        await session.commit()


async def test_round_robin_rotates_managers(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    automation_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipeline = await default_pipeline(client)
        await make_manager(client, token)
        await make_manager(client, token)
        async with factory() as session:
            roster = (
                (
                    await session.execute(
                        text(
                            "SELECT id::text FROM crm_users WHERE role = 'manager'"
                            " AND is_active ORDER BY created_at, id"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(roster) >= 2
        await _set_assignment(factory, "round_robin")
        try:
            owners = []
            for _ in range(len(roster) + 1):
                contact = await create_contact(client, token, whatsapp_id=_wa())
                contact_ids.append(contact["id"])
                deal = await create_deal(client, token, contact["id"], pipeline)
                owners.append(deal["owner_id"])
            assert all(owner in roster for owner in owners)
            assert len(set(owners)) == len(roster)
            assert owners[-1] == owners[0]
        finally:
            await _clear_assignment(factory)
    finally:
        for automation_id in automation_ids:
            await client.delete(f"/api/automations/{automation_id}", headers=csrf_headers(token))
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_unassigned_default_and_deal_assigned_notify(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    automation_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipeline = await default_pipeline(client)
        manager = await make_manager(client, token)
        contact = await create_contact(client, token, whatsapp_id=_wa())
        contact_ids.append(contact["id"])

        plain = await create_deal(client, token, contact["id"], pipeline)
        assert plain["owner_id"] is None

        owned = await create_deal(
            client, token, contact["id"], pipeline, owner_id=manager["user"]["id"]
        )
        assert owned["owner_id"] == manager["user"]["id"]
        async with factory() as session:
            note = (
                await session.execute(
                    text(
                        "SELECT type FROM crm_notifications n JOIN crm_users u ON u.id = n.user_id"
                        " WHERE u.email = :email ORDER BY n.created_at DESC LIMIT 1"
                    ),
                    {"email": manager["email"]},
                )
            ).scalar_one()
            assert note == "deal_assigned"
            await session.execute(text("DELETE FROM crm_notifications"))
            await session.commit()
    finally:
        for automation_id in automation_ids:
            await client.delete(f"/api/automations/{automation_id}", headers=csrf_headers(token))
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_overdue_and_due_soon_idempotent(client, settings):
    from datetime import UTC, datetime, timedelta

    from backend.app.workers.notify_worker import run_notify_cycle

    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    automation_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        manager = await make_manager(client, token)
        contact = await create_contact(client, token, whatsapp_id=_wa())
        contact_ids.append(contact["id"])
        for title, due in (
            ("Overdue one", "2020-01-01T00:00:00Z"),
            ("Due soon one", "2030-01-01T00:00:00Z"),
        ):
            created = await client.post(
                "/api/tasks",
                json={
                    "contact_id": contact["id"],
                    "title": title,
                    "assignee_id": manager["user"]["id"],
                    "due_at": due,
                },
                headers=csrf_headers(token),
            )
            assert created.status_code == 201

        soon_at = datetime.now(UTC) + timedelta(hours=2)
        async with factory() as session:
            await session.execute(
                text("UPDATE crm_tasks SET due_at = :due WHERE title = 'Due soon one'"),
                {"due": soon_at},
            )
            await session.commit()

        first = await run_notify_cycle(factory)
        assert first["overdue"] >= 1
        assert first["due_soon"] >= 1
        await run_notify_cycle(factory)
        async with factory() as session:
            mine = (
                await session.execute(
                    text(
                        "SELECT type, COUNT(*) FROM crm_notifications n JOIN crm_users u"
                        " ON u.id = n.user_id WHERE u.email = :email GROUP BY type"
                    ),
                    {"email": manager["email"]},
                )
            ).all()
            mine = {row[0]: row[1] for row in mine}
            assert mine.get("task_overdue") == 1
            assert mine.get("task_due_soon") == 1
            await session.execute(
                text(
                    "DELETE FROM crm_notifications WHERE user_id = (SELECT id FROM crm_users"
                    " WHERE email = :email)"
                ),
                {"email": manager["email"]},
            )
            await session.commit()
    finally:
        for automation_id in automation_ids:
            await client.delete(f"/api/automations/{automation_id}", headers=csrf_headers(token))
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_automations_crud_and_fire_once(client, settings, app):
    from backend.app.services.automations import evaluate_automations

    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    automation_ids: list[str] = []
    pipeline_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipe = (
            await client.post(
                "/api/pipelines",
                json={"name": f"Auto pipe {uuid.uuid4().hex[:8]}"},
                headers=csrf_headers(token),
            )
        ).json()
        pipeline_ids.append(pipe["id"])
        stage = (
            await client.post(
                f"/api/pipelines/{pipe['id']}/stages",
                json={"name": "Entry"},
                headers=csrf_headers(token),
            )
        ).json()
        manager = await make_manager(client, token)

        created = await client.post(
            "/api/automations",
            json={
                "name": "Welcome task",
                "trigger_type": "deal_entered_stage",
                "trigger_config": {"stage_id": stage["id"], "pipeline_id": pipe["id"]},
                "actions": [
                    {"type": "create_task", "title": "Welcome client", "due_in_hours": 24},
                    {"type": "notify", "to": "owner", "text": "New deal in stage"},
                ],
            },
            headers=csrf_headers(token),
        )
        assert created.status_code == 201
        automation_id = created.json()["id"]
        automation_ids.append(automation_id)

        contact = await create_contact(client, token, whatsapp_id=_wa())
        contact_ids.append(contact["id"])
        deal = await create_deal(
            client,
            token,
            contact["id"],
            {**pipe, "stages": [stage]},
            pipeline_id=pipe["id"],
            stage_id=stage["id"],
            owner_id=manager["user"]["id"],
        )

        async with factory() as session:
            stats = await evaluate_automations(session)
            await session.commit()
        assert stats.fired == 1

        async with factory() as session:
            task_titles = (
                (
                    await session.execute(
                        text("SELECT title FROM crm_tasks WHERE deal_id = :id"), {"id": deal["id"]}
                    )
                )
                .scalars()
                .all()
            )
            assert "Welcome client" in task_titles
            fired_marks = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM crm_activity_log WHERE entity = 'deal'"
                        " AND entity_id = :id AND action = 'automation_fired'"
                    ),
                    {"id": deal["id"]},
                )
            ).scalar()
            assert fired_marks == 1
            again = await evaluate_automations(session)
            await session.commit()
        assert again.fired == 0

        async with ManagerSession(app, manager["email"], manager["password"]) as mgr:
            assert mgr.client is not None
            forbidden = await mgr.client.post(
                "/api/automations",
                json={"name": "x", "trigger_type": "deal_entered_stage"},
                headers=mgr.headers(),
            )
            assert forbidden.status_code == 403
            visible = await mgr.client.get("/api/automations")
            assert any(a["id"] == automation_id for a in visible.json())

        gone = await client.delete(f"/api/automations/{automation_id}", headers=csrf_headers(token))
        assert gone.json() == {"ok": True}
        automation_ids.remove(automation_id)
    finally:
        for automation_id in automation_ids:
            await client.delete(f"/api/automations/{automation_id}", headers=csrf_headers(token))
        from backend.tests.crm_helpers import purge_pipelines

        await purge_contacts(factory, contact_ids)
        await purge_pipelines(factory, pipeline_ids)
        await engine.dispose()


async def test_no_activity_automation(client, settings):
    from datetime import UTC, datetime, timedelta

    from backend.app.services.automations import evaluate_automations

    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    automation_ids: list[str] = []
    pipeline_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipe = (
            await client.post(
                "/api/pipelines",
                json={"name": f"Stale pipe {uuid.uuid4().hex[:8]}"},
                headers=csrf_headers(token),
            )
        ).json()
        pipeline_ids.append(pipe["id"])
        stage = (
            await client.post(
                f"/api/pipelines/{pipe['id']}/stages",
                json={"name": "Entry"},
                headers=csrf_headers(token),
            )
        ).json()
        created = await client.post(
            "/api/automations",
            json={
                "name": "Stale nudge",
                "trigger_type": "no_activity_hours",
                "trigger_config": {"hours": 1, "pipeline_id": pipe["id"]},
                "actions": [{"type": "add_tag", "tag_id": str(uuid.uuid4())}],
            },
            headers=csrf_headers(token),
        )
        automation_id = created.json()["id"]
        automation_ids.append(automation_id)

        contact = await create_contact(client, token, whatsapp_id=_wa())
        contact_ids.append(contact["id"])
        deal = await create_deal(
            client,
            token,
            contact["id"],
            {**pipe, "stages": [stage]},
            pipeline_id=pipe["id"],
            stage_id=stage["id"],
        )
        stale = datetime.now(UTC) - timedelta(hours=5)
        async with factory() as session:
            await session.execute(
                text("UPDATE crm_deals SET updated_at = :at WHERE id = :id"),
                {"at": stale, "id": deal["id"]},
            )
            await session.commit()
            stats = await evaluate_automations(session)
            await session.commit()
        # Tag id is random/unknown so the action is skipped, but firing is recorded.
        assert stats.fired == 1
        async with factory() as session:
            stats = await evaluate_automations(session)
            await session.commit()
        assert stats.fired == 0

        await client.delete(f"/api/automations/{automation_id}", headers=csrf_headers(token))
        automation_ids.remove(automation_id)
    finally:
        for automation_id in automation_ids:
            await client.delete(f"/api/automations/{automation_id}", headers=csrf_headers(token))
        from backend.tests.crm_helpers import purge_pipelines

        await purge_contacts(factory, contact_ids)
        await purge_pipelines(factory, pipeline_ids)
        await engine.dispose()
