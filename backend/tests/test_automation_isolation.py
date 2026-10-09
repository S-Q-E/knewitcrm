from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from backend.app.workers.notify_worker import run_notify_cycle
from backend.tests.conftest import csrf_headers
from backend.tests.crm_helpers import (
    admin_csrf,
    engine_factory,
    make_manager,
    purge_contacts,
    run_sync,
)

pytestmark = pytest.mark.usefixtures("db_available")


def _wa() -> str:
    return f"7999{uuid.uuid4().hex[:8]}@c.us"


async def _lead_with_deal(factory, wa: str) -> tuple[str, str]:
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO knewit_leads (whatsapp_id, name, current_stage, status)"
                " VALUES (:wa, 'Iso Bot', 'НОВЫЙ_ЛИД', 'ACTIVE')"
            ),
            {"wa": wa},
        )
        await session.commit()
    await run_sync(factory)
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT d.id, d.stage_id FROM crm_deals d"
                    " JOIN crm_contacts c ON c.id = d.contact_id WHERE c.whatsapp_id = :wa"
                ),
                {"wa": wa},
            )
        ).one()
    return str(row[0]), str(row[1])


async def _cleanup(factory, wa: str, automation_ids: list[str], tag_ids: list[str], task_id: str):
    async with factory() as session:
        for automation_id in automation_ids:
            await session.execute(
                text("DELETE FROM crm_automations WHERE id = :id"), {"id": automation_id}
            )
        for tag_id in tag_ids:
            await session.execute(
                text("DELETE FROM crm_entity_tags WHERE tag_id = :id"), {"id": tag_id}
            )
            await session.execute(text("DELETE FROM crm_tags WHERE id = :id"), {"id": tag_id})
        await session.execute(
            text("DELETE FROM crm_notifications WHERE payload->>'task_id' = :id"), {"id": task_id}
        )
        await session.execute(text("DELETE FROM crm_tasks WHERE id = :id"), {"id": task_id})
        await session.execute(
            text("DELETE FROM crm_conversation_state WHERE whatsapp_id = :wa"), {"wa": wa}
        )
        await session.execute(
            text("DELETE FROM knewit_messages WHERE whatsapp_id = :wa"), {"wa": wa}
        )
        await session.execute(text("DELETE FROM knewit_events WHERE whatsapp_id = :wa"), {"wa": wa})
        await session.execute(text("DELETE FROM knewit_leads WHERE whatsapp_id = :wa"), {"wa": wa})
        await session.commit()
        contacts = (
            (
                await session.execute(
                    text("SELECT id FROM crm_contacts WHERE whatsapp_id = :wa"), {"wa": wa}
                )
            )
            .scalars()
            .all()
        )
    await purge_contacts(factory, [str(c) for c in contacts])


async def _add_overdue_task(factory, assignee_id: str) -> str:
    task_id = str(uuid.uuid4())
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO crm_tasks (id, title, type, due_at, assignee_id)"
                " VALUES (:id, 'B06 overdue', 'message', :due, :assignee)"
            ),
            {
                "id": task_id,
                "due": datetime.now(UTC) - timedelta(hours=1),
                "assignee": assignee_id,
            },
        )
        await session.commit()
    return task_id


async def _add_automation(factory, stage_id: str, actions: list[dict]) -> str:
    automation_id = str(uuid.uuid4())
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO crm_automations (id, name, is_active, trigger_type, trigger_config,"
                " actions) VALUES (:id, 'B06 automation', TRUE, 'deal_entered_stage',"
                " CAST(:config AS jsonb), CAST(:actions AS jsonb))"
            ),
            {
                "id": automation_id,
                "config": json.dumps({"stage_id": stage_id}),
                "actions": json.dumps(actions),
            },
        )
        await session.commit()
    return automation_id


async def _overdue_count(factory, task_id: str) -> int:
    async with factory() as session:
        return (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM crm_notifications"
                    " WHERE type = 'task_overdue' AND payload->>'task_id' = :id"
                ),
                {"id": task_id},
            )
        ).scalar_one()


async def test_duplicate_tag_action_does_not_stop_notify_cycle(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    automation_ids: list[str] = []
    tag_ids: list[str] = []
    task_id = ""
    try:
        token = await admin_csrf(client, settings)
        manager = await make_manager(client, token)
        deal_id, stage_id = await _lead_with_deal(factory, wa)
        tag_id = str(uuid.uuid4())
        tag_ids.append(tag_id)
        async with factory() as session:
            await session.execute(
                text("INSERT INTO crm_tags (id, name) VALUES (:id, :name)"),
                {"id": tag_id, "name": f"b06-{tag_id[:8]}"},
            )
            await session.execute(
                text(
                    "INSERT INTO crm_entity_tags (id, tag_id, entity, entity_id)"
                    " VALUES (:id, :tag, 'deal', :deal)"
                ),
                {"id": str(uuid.uuid4()), "tag": tag_id, "deal": deal_id},
            )
            await session.commit()
        automation_ids.append(
            await _add_automation(factory, stage_id, [{"type": "add_tag", "tag_id": tag_id}])
        )
        task_id = await _add_overdue_task(factory, manager["user"]["id"])

        await run_notify_cycle(factory)

        assert await _overdue_count(factory, task_id) == 1
    finally:
        await _cleanup(factory, wa, automation_ids, tag_ids, task_id)
        await engine.dispose()


async def test_unknown_owner_action_does_not_stop_notify_cycle(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    automation_ids: list[str] = []
    task_id = ""
    try:
        token = await admin_csrf(client, settings)
        manager = await make_manager(client, token)
        _, stage_id = await _lead_with_deal(factory, wa)
        automation_ids.append(
            await _add_automation(
                factory,
                stage_id,
                [{"type": "assign_owner", "user_id": str(uuid.uuid4())}],
            )
        )
        task_id = await _add_overdue_task(factory, manager["user"]["id"])

        await run_notify_cycle(factory)

        assert await _overdue_count(factory, task_id) == 1
    finally:
        await _cleanup(factory, wa, automation_ids, [], task_id)
        await engine.dispose()


async def test_automation_create_rejects_unknown_tag_and_user(client, settings):
    token = await admin_csrf(client, settings)
    headers = csrf_headers(token)
    unknown = str(uuid.uuid4())
    body = {
        "name": "B06 validation",
        "trigger_type": "no_activity_hours",
        "trigger_config": {"hours": 24},
    }
    tag_case = await client.post(
        "/api/automations",
        json={**body, "actions": [{"type": "add_tag", "tag_id": unknown}]},
        headers=headers,
    )
    assert tag_case.status_code == 422, tag_case.text
    owner_case = await client.post(
        "/api/automations",
        json={**body, "actions": [{"type": "assign_owner", "user_id": unknown}]},
        headers=headers,
    )
    assert owner_case.status_code == 422, owner_case.text
    malformed = await client.post(
        "/api/automations",
        json={**body, "actions": [{"type": "assign_owner", "user_id": "not-a-uuid"}]},
        headers=headers,
    )
    assert malformed.status_code == 422, malformed.text
