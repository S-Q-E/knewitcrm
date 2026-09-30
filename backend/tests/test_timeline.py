from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from backend.tests.conftest import csrf_headers
from backend.tests.crm_helpers import (
    admin_csrf,
    create_contact,
    create_deal,
    default_pipeline,
    engine_factory,
    purge_contacts,
)

pytestmark = pytest.mark.usefixtures("db_available")


def _wa() -> str:
    return f"7999{uuid.uuid4().hex[:8]}@c.us"


async def _seed_bot_history(factory, wa: str) -> None:
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO knewit_leads (whatsapp_id, name, current_stage, status)"
                " VALUES (:wa, 'Timeline Bot', 'НОВЫЙ_ЛИД', 'ACTIVE')"
            ),
            {"wa": wa},
        )
        await session.execute(
            text(
                "INSERT INTO knewit_messages (whatsapp_id, direction, message_type, content)"
                " VALUES (:wa, 'in', 'chat', 'Hello'), (:wa, 'out', 'chat', 'Hi there')"
            ),
            {"wa": wa},
        )
        await session.execute(
            text(
                "INSERT INTO knewit_events (whatsapp_id, event_type, to_stage, payload)"
                " VALUES (:wa, 'stage_entered', 'НОВЫЙ_ЛИД', '{}')"
            ),
            {"wa": wa},
        )
        await session.commit()


async def test_timeline_merges_and_orders(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipeline = await default_pipeline(client)
        wa = _wa()
        await _seed_bot_history(factory, wa)
        contact = await create_contact(client, token, whatsapp_id=wa, name="Timeline Bot")
        contact_ids.append(contact["id"])
        deal = await create_deal(client, token, contact["id"], pipeline, title="Timeline Deal")

        note = await client.post(
            "/api/notes",
            json={"deal_id": deal["id"], "body": "Manager note"},
            headers=csrf_headers(token),
        )
        assert note.status_code == 201
        task = await client.post(
            "/api/tasks",
            json={"deal_id": deal["id"], "title": "Follow up"},
            headers=csrf_headers(token),
        )
        assert task.status_code == 201

        response = await client.get(f"/api/deals/{deal['id']}/timeline?limit=100")
        assert response.status_code == 200
        body = response.json()
        kinds = [item["kind"] for item in body["items"]]
        for expected in ("message", "event", "stage", "note", "task", "activity"):
            assert expected in kinds, f"missing {expected}: {kinds}"

        # Newest first.
        stamps = [item["at"] for item in body["items"]]
        assert stamps == sorted(stamps, reverse=True)

        message = next(
            i for i in body["items"] if i["kind"] == "message" and i["data"]["direction"] == "in"
        )
        assert message["data"]["author_name"] == "Timeline Bot"
        outgoing = next(
            i for i in body["items"] if i["kind"] == "message" and i["data"]["direction"] == "out"
        )
        assert outgoing["data"]["author_name"] == "Бот"
        stage = next(i for i in body["items"] if i["kind"] == "stage")
        assert stage["data"]["to_stage"]["name"]
        assert stage["data"]["source"] == "manager"
        assert stage["data"]["changed_by_name"]
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_timeline_types_filter_and_cursor(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipeline = await default_pipeline(client)
        wa = _wa()
        await _seed_bot_history(factory, wa)
        contact = await create_contact(client, token, whatsapp_id=wa)
        contact_ids.append(contact["id"])
        deal = await create_deal(client, token, contact["id"], pipeline)

        bad = await client.get(f"/api/deals/{deal['id']}/timeline?types=nope")
        assert bad.status_code == 422

        messages_only = await client.get(f"/api/deals/{deal['id']}/timeline?types=message&limit=1")
        assert messages_only.status_code == 200
        first = messages_only.json()
        assert len(first["items"]) == 1
        assert first["items"][0]["kind"] == "message"
        assert first["next_cursor"]

        second = await client.get(
            f"/api/deals/{deal['id']}/timeline?types=message&limit=1&cursor={first['next_cursor']}"
        )
        assert second.status_code == 200
        second_body = second.json()
        assert len(second_body["items"]) == 1
        assert second_body["items"][0]["key"] != first["items"][0]["key"]

        bad_cursor = await client.get(f"/api/deals/{deal['id']}/timeline?cursor=bogus")
        assert bad_cursor.status_code == 422

        missing = await client.get("/api/deals/00000000-0000-0000-0000-000000000000/timeline")
        assert missing.status_code == 404
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()
