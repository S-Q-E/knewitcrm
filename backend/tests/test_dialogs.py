from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from backend.tests.conftest import csrf_headers
from backend.tests.crm_helpers import (
    admin_csrf,
    engine_factory,
    make_manager,
    run_sync,
)

pytestmark = pytest.mark.usefixtures("db_available")


def _wa() -> str:
    return f"7999{uuid.uuid4().hex[:8]}@c.us"


async def _insert_lead(factory, wa: str) -> None:
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO knewit_leads (whatsapp_id, name, current_stage, status)"
                " VALUES (:wa, 'Dialog Bot', 'НОВЫЙ_ЛИД', 'ACTIVE')"
            ),
            {"wa": wa},
        )
        await session.execute(
            text(
                "INSERT INTO knewit_messages (whatsapp_id, direction, message_type, content)"
                " VALUES (:wa, 'in', 'chat', 'Hello manager')"
            ),
            {"wa": wa},
        )
        await session.commit()


async def _purge_lead(factory, wa: str) -> None:
    from backend.tests.crm_helpers import purge_contacts

    async with factory() as session:
        contacts = (
            (
                await session.execute(
                    text("SELECT id FROM crm_contacts WHERE whatsapp_id = :wa"), {"wa": wa}
                )
            )
            .scalars()
            .all()
        )
        await session.execute(
            text("DELETE FROM crm_conversation_state WHERE whatsapp_id = :wa"), {"wa": wa}
        )
        await session.execute(text("DELETE FROM crm_outbox WHERE whatsapp_id = :wa"), {"wa": wa})
        await session.execute(
            text("DELETE FROM knewit_messages WHERE whatsapp_id = :wa"), {"wa": wa}
        )
        await session.execute(text("DELETE FROM knewit_events WHERE whatsapp_id = :wa"), {"wa": wa})
        await session.execute(text("DELETE FROM knewit_leads WHERE whatsapp_id = :wa"), {"wa": wa})
        await session.commit()
    await purge_contacts(factory, [str(c) for c in contacts])


async def test_dialog_messages_route_with_auth(client, settings):
    from backend.tests.crm_helpers import run_sync

    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        await admin_csrf(client, settings)
        await _insert_lead(factory, wa)
        await run_sync(factory)

        response = await client.get(f"/api/dialogs/{wa}/messages?limit=500")
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 1
        assert set(items[0]) == {
            "id",
            "direction",
            "message_type",
            "content",
            "stage_at_moment",
            "created_at",
        }
        assert items[0]["content"] == "Hello manager"

        missing = await client.get("/api/dialogs/unknown@c.us/messages")
        assert missing.status_code == 404
    finally:
        await _purge_lead(factory, wa)
        await engine.dispose()


async def test_dialogs_list_read_and_unread(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        token = await admin_csrf(client, settings)
        await _insert_lead(factory, wa)
        await run_sync(factory)

        dialogs = await client.get("/api/dialogs")
        assert dialogs.status_code == 200
        mine = next((d for d in dialogs.json()["items"] if d["whatsapp_id"] == wa), None)
        assert mine is not None
        assert mine["contact_name"] == "Dialog Bot"
        assert mine["unread_count"] == 0
        assert mine["last_message"]["content"] == "Hello manager"

        # A new incoming message bumps unread on the next sync.
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO knewit_messages (whatsapp_id, direction, message_type,"
                    " content, created_at) VALUES (:wa, 'in', 'chat', 'Are you there?',"
                    " now() + interval '1 second')"
                ),
                {"wa": wa},
            )
            # The bot also touches the lead row, which is what the sync watches.
            await session.execute(
                text(
                    "UPDATE knewit_leads SET last_message_at = now(), updated_at = now()"
                    " WHERE whatsapp_id = :wa"
                ),
                {"wa": wa},
            )
            await session.commit()
        await run_sync(factory)
        dialogs = await client.get("/api/dialogs?unread=true")
        bumped = next((d for d in dialogs.json()["items"] if d["whatsapp_id"] == wa), None)
        assert bumped is not None and bumped["unread_count"] == 1

        read = await client.post(f"/api/dialogs/{wa}/read", headers=csrf_headers(token))
        assert read.json() == {"ok": True, "whatsapp_id": wa}
        dialogs = await client.get("/api/dialogs?unread=true")
        assert all(d["whatsapp_id"] != wa for d in dialogs.json()["items"])
    finally:
        await _purge_lead(factory, wa)
        await engine.dispose()


async def test_dialog_assign_and_pause(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        token = await admin_csrf(client, settings)
        manager = await make_manager(client, token)
        await _insert_lead(factory, wa)
        await run_sync(factory)

        patched = await client.patch(
            f"/api/dialogs/{wa}",
            json={"assigned_to": manager["user"]["id"], "bot_paused": True},
            headers=csrf_headers(token),
        )
        assert patched.status_code == 200
        body = patched.json()
        assert body["assigned_to"] == manager["user"]["id"]
        assert body["bot_paused"] is True
        assert body["assignee_name"] == manager["user"]["name"]

        mine = await client.get("/api/dialogs?assigned=mine")
        assert mine.status_code == 200

        bad_user = await client.patch(
            f"/api/dialogs/{wa}",
            json={"assigned_to": "00000000-0000-0000-0000-000000000000"},
            headers=csrf_headers(token),
        )
        assert bad_user.status_code == 422

        missing = await client.get("/api/dialogs/unknown@c.us")
        assert missing.status_code == 404
    finally:
        await _purge_lead(factory, wa)
        await engine.dispose()


async def test_dialog_messages_returns_newest_window_and_pages_back(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        await admin_csrf(client, settings)
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO knewit_leads (whatsapp_id, name, current_stage, status)"
                    " VALUES (:wa, 'Long Bot', 'НОВЫЙ_ЛИД', 'ACTIVE')"
                ),
                {"wa": wa},
            )
            await session.execute(
                text(
                    "INSERT INTO knewit_messages"
                    " (whatsapp_id, direction, message_type, content, created_at)"
                    " SELECT :wa, 'in', 'chat', 'msg-' || g,"
                    " now() - make_interval(secs => 600 - g)"
                    " FROM generate_series(1, 600) AS g"
                ),
                {"wa": wa},
            )
            await session.commit()

        newest = await client.get(f"/api/dialogs/{wa}/messages?limit=500")
        assert newest.status_code == 200, newest.text
        body = newest.json()
        contents = [item["content"] for item in body["items"]]
        assert len(contents) == 500
        assert contents[0] == "msg-101"
        assert contents[-1] == "msg-600"
        assert body["has_more"] is True

        older = await client.get(
            f"/api/dialogs/{wa}/messages?limit=500&before_id={body['items'][0]['id']}"
        )
        assert older.status_code == 200, older.text
        older_body = older.json()
        older_contents = [item["content"] for item in older_body["items"]]
        assert older_contents == [f"msg-{n}" for n in range(1, 101)]
        assert older_body["has_more"] is False
    finally:
        await _purge_lead(factory, wa)
        await engine.dispose()


async def test_read_and_patch_refuse_a_dialog_without_a_bot_lead(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        token = await admin_csrf(client, settings)
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO crm_conversation_state (whatsapp_id, bot_paused)"
                    " VALUES (:wa, FALSE)"
                ),
                {"wa": wa},
            )
            await session.commit()

        read = await client.post(f"/api/dialogs/{wa}/read", headers=csrf_headers(token))
        assert read.status_code == 404, read.text
        assert read.json()["error"]["code"] == "LEAD_NOT_FOUND"
        patched = await client.patch(
            f"/api/dialogs/{wa}", json={"bot_paused": True}, headers=csrf_headers(token)
        )
        assert patched.status_code == 404, patched.text
        assert patched.json()["error"]["code"] == "LEAD_NOT_FOUND"
        async with factory() as session:
            paused = (
                await session.execute(
                    text("SELECT bot_paused FROM crm_conversation_state WHERE whatsapp_id = :wa"),
                    {"wa": wa},
                )
            ).scalar_one()
        assert paused is False
    finally:
        async with factory() as session:
            await session.execute(
                text("DELETE FROM crm_conversation_state WHERE whatsapp_id = :wa"), {"wa": wa}
            )
            await session.commit()
        await engine.dispose()
