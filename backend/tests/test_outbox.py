from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from sqlalchemy import text

from backend.app.config import Settings
from backend.app.workers.outbox_worker import (
    N8N_SECRET_HEADER,
    OUTBOX_MAX_ATTEMPTS,
    N8nError,
    OutboxConfigError,
    post_to_n8n,
    run_outbox_cycle,
)
from backend.tests.conftest import csrf_headers, login_admin
from backend.tests.crm_helpers import admin_csrf, engine_factory, make_manager, run_sync

pytestmark = pytest.mark.usefixtures("db_available")


def _wa() -> str:
    return f"7999{uuid.uuid4().hex[:8]}@c.us"


async def _insert_lead(factory, wa: str) -> None:
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO knewit_leads (whatsapp_id, name, current_stage, status)"
                " VALUES (:wa, 'Outbox Bot', 'НОВЫЙ_ЛИД', 'ACTIVE')"
            ),
            {"wa": wa},
        )
        await session.commit()


async def _outbox_row(factory, wa: str) -> dict | None:
    async with factory() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT id, whatsapp_id, status, attempts, error,"
                        " provider_message_id, knewit_message_id, sent_at,"
                        " next_attempt_at FROM crm_outbox"
                        " WHERE whatsapp_id = :wa ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"wa": wa},
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None


async def _force_due(factory, outbox_id: str) -> None:
    async with factory() as session:
        await session.execute(
            text(
                "UPDATE crm_outbox SET next_attempt_at = now() - interval '1 second'"
                " WHERE id = :id"
            ),
            {"id": outbox_id},
        )
        await session.commit()


async def _purge(factory, wa: str, user_ids: list[str]) -> None:
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
        await session.execute(text("DELETE FROM crm_outbox WHERE whatsapp_id = :wa"), {"wa": wa})
        if user_ids:
            await session.execute(
                text("DELETE FROM crm_notifications WHERE user_id = ANY(:ids)"),
                {"ids": user_ids},
            )
        # Delete the bot lead directly (cascades to messages/events):
        # purge_contacts skips lead cleanup when no contact exists, and most
        # outbox tests never run the sync that would create one.
        await session.execute(text("DELETE FROM knewit_leads WHERE whatsapp_id = :wa"), {"wa": wa})
        await session.commit()
    await purge_contacts(factory, [str(c) for c in contacts])


def _ok_sender(provider_id: str = "pv-1"):
    calls: list[dict] = []

    async def sender(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "provider_message_id": provider_id}

    sender.calls = calls
    return sender


def _flaky_sender(fail_times: int):
    calls: list[dict] = []

    async def sender(**kwargs):
        calls.append(kwargs)
        if len(calls) <= fail_times:
            raise RuntimeError("n8n exploded")
        return {"ok": True, "provider_message_id": "pv-9"}

    sender.calls = calls
    return sender


async def test_queue_message_returns_202_and_autopauses(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        token = await admin_csrf(client, settings)
        await _insert_lead(factory, wa)
        response = await client.post(
            f"/api/chats/{wa}/messages", json={"body": "Здравствуйте!"}, headers=csrf_headers(token)
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["whatsapp_id"] == wa
        assert body["status"] == "queued"
        assert body["attempts"] == 0

        async with factory() as session:
            paused = (
                await session.execute(
                    text("SELECT bot_paused FROM crm_conversation_state WHERE whatsapp_id = :wa"),
                    {"wa": wa},
                )
            ).scalar()
            assert paused is True
            logged = (
                await session.execute(
                    text(
                        "SELECT action FROM crm_activity_log WHERE action = 'bot_paused'"
                        " AND diff ->> 'whatsapp_id' = :wa"
                    ),
                    {"wa": wa},
                )
            ).scalar_one_or_none()
            assert logged == "bot_paused"
    finally:
        await _purge(factory, wa, [])
        await engine.dispose()


async def test_queue_rejects_empty_body_and_unknown_dialog(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        token = await admin_csrf(client, settings)
        await _insert_lead(factory, wa)
        empty = await client.post(
            f"/api/chats/{wa}/messages", json={"body": "   "}, headers=csrf_headers(token)
        )
        assert empty.status_code == 422
        missing = await client.post(
            "/api/chats/unknown@c.us/messages",
            json={"body": "hi"},
            headers=csrf_headers(token),
        )
        assert missing.status_code == 404
    finally:
        await _purge(factory, wa, [])
        await engine.dispose()


async def test_worker_sends_mirrors_and_is_idempotent(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        token = await admin_csrf(client, settings)
        await _insert_lead(factory, wa)
        queued = await client.post(
            f"/api/chats/{wa}/messages",
            json={"body": "Приходите завтра"},
            headers=csrf_headers(token),
        )
        assert queued.status_code == 202

        sender = _ok_sender()
        stats = await run_outbox_cycle(factory, settings, sender=sender)
        assert stats is not None and stats["sent"] == 1
        assert len(sender.calls) == 1
        assert sender.calls[0]["whatsapp_id"] == wa
        assert sender.calls[0]["text"] == "Приходите завтра"

        row = await _outbox_row(factory, wa)
        assert row is not None
        assert row["status"] == "sent"
        assert row["provider_message_id"] == "pv-1"
        assert row["sent_at"] is not None
        assert row["knewit_message_id"] is not None

        async with factory() as session:
            mirrored = (
                (
                    await session.execute(
                        text(
                            "SELECT direction, message_type, content, stage_at_moment,"
                            " tokens_used FROM knewit_messages WHERE id = :id"
                        ),
                        {"id": row["knewit_message_id"]},
                    )
                )
                .mappings()
                .one()
            )
            assert mirrored["direction"] == "out"
            assert mirrored["message_type"] == "manager"
            assert mirrored["content"] == "Приходите завтра"
            assert mirrored["stage_at_moment"] == "НОВЫЙ_ЛИД"
            assert mirrored["tokens_used"] == 0

        # A repeated run must not resend (idempotent by outbox_id).
        again = await run_outbox_cycle(factory, settings, sender=sender)
        assert again is not None and again["sent"] == 0
        assert len(sender.calls) == 1
        async with factory() as session:
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM knewit_messages"
                        " WHERE whatsapp_id = :wa AND message_type = 'manager'"
                    ),
                    {"wa": wa},
                )
            ).scalar()
            assert count == 1
    finally:
        await _purge(factory, wa, [])
        await engine.dispose()


async def test_worker_retries_then_succeeds(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        token = await admin_csrf(client, settings)
        await _insert_lead(factory, wa)
        queued = await client.post(
            f"/api/chats/{wa}/messages", json={"body": "Ждём вас"}, headers=csrf_headers(token)
        )
        assert queued.status_code == 202

        sender = _flaky_sender(fail_times=2)
        first = await run_outbox_cycle(factory, settings, sender=sender)
        assert first is not None and first["pending_retry"] == 1
        row = await _outbox_row(factory, wa)
        assert row is not None and row["status"] == "queued" and row["attempts"] == 1
        assert row["next_attempt_at"] is not None and row["error"]

        await _force_due(factory, row["id"])
        second = await run_outbox_cycle(factory, settings, sender=sender)
        assert second is not None and second["pending_retry"] == 1
        row = await _outbox_row(factory, wa)
        assert row is not None and row["attempts"] == 2

        await _force_due(factory, row["id"])
        third = await run_outbox_cycle(factory, settings, sender=sender)
        assert third is not None and third["sent"] == 1
        row = await _outbox_row(factory, wa)
        assert row is not None and row["status"] == "sent"
        assert len(sender.calls) == 3
    finally:
        await _purge(factory, wa, [])
        await engine.dispose()


async def test_worker_fails_after_five_attempts_and_notifies(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    admin = await login_admin(client, settings)
    try:
        await _insert_lead(factory, wa)
        queued = await client.post(
            f"/api/chats/{wa}/messages",
            json={"body": "Не дойдёт"},
            headers=csrf_headers(admin["csrf"]),
        )
        assert queued.status_code == 202

        async def always_fail(**kwargs):
            raise RuntimeError("n8n is down")

        for _ in range(OUTBOX_MAX_ATTEMPTS):
            stats = await run_outbox_cycle(factory, settings, sender=always_fail)
            assert stats is not None
            row = await _outbox_row(factory, wa)
            assert row is not None
            if row["status"] != "failed":
                await _force_due(factory, row["id"])
        row = await _outbox_row(factory, wa)
        assert row is not None
        assert row["status"] == "failed"
        assert row["attempts"] == OUTBOX_MAX_ATTEMPTS
        assert row["error"]

        async with factory() as session:
            notes = (
                (
                    await session.execute(
                        text(
                            "SELECT type, payload FROM crm_notifications"
                            " WHERE user_id = :id ORDER BY created_at"
                        ),
                        {"id": admin["user"]["id"]},
                    )
                )
                .mappings()
                .all()
            )
            failed = [n for n in notes if n["type"] == "outbox_failed"]
            assert len(failed) == 1
            assert failed[0]["payload"]["whatsapp_id"] == wa
    finally:
        await _purge(factory, wa, [admin["user"]["id"]])
        await engine.dispose()


async def test_pause_resume_endpoints_and_timeline(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        token = await admin_csrf(client, settings)
        await _insert_lead(factory, wa)
        await run_sync(factory)
        async with factory() as session:
            deal_id = (
                await session.execute(
                    text(
                        "SELECT d.id FROM crm_deals d JOIN crm_contacts c ON c.id = d.contact_id"
                        " WHERE c.whatsapp_id = :wa"
                    ),
                    {"wa": wa},
                )
            ).scalar_one()

        paused = await client.post(f"/api/chats/{wa}/bot/pause", headers=csrf_headers(token))
        assert paused.status_code == 200
        assert paused.json()["bot_paused"] is True
        assert paused.json()["paused_by"] is not None

        # Idempotent: pausing twice logs a single timeline event.
        paused_again = await client.post(f"/api/chats/{wa}/bot/pause", headers=csrf_headers(token))
        assert paused_again.json()["bot_paused"] is True

        resumed = await client.post(f"/api/chats/{wa}/bot/resume", headers=csrf_headers(token))
        assert resumed.status_code == 200
        assert resumed.json()["bot_paused"] is False
        assert resumed.json()["paused_by"] is None

        timeline = await client.get(f"/api/deals/{deal_id}/timeline?types=activity&limit=50")
        assert timeline.status_code == 200
        actions = [item["data"].get("action") for item in timeline.json()["items"]]
        assert actions.count("bot_paused") == 1
        assert actions.count("bot_resumed") == 1
    finally:
        await _purge(factory, wa, [])
        await engine.dispose()


async def test_autopause_disabled_via_setting(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        token = await admin_csrf(client, settings)
        await _insert_lead(factory, wa)
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO crm_settings (key, value) VALUES"
                    " ('auto_pause_on_manual_reply', 'false')"
                    " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
                )
            )
            await session.commit()
        try:
            response = await client.post(
                f"/api/chats/{wa}/messages",
                json={"body": "Без паузы"},
                headers=csrf_headers(token),
            )
            assert response.status_code == 202
            async with factory() as session:
                paused = (
                    await session.execute(
                        text(
                            "SELECT bot_paused FROM crm_conversation_state WHERE whatsapp_id = :wa"
                        ),
                        {"wa": wa},
                    )
                ).scalar()
                assert paused is False
        finally:
            async with factory() as session:
                await session.execute(
                    text("DELETE FROM crm_settings WHERE key = 'auto_pause_on_manual_reply'")
                )
                await session.commit()
    finally:
        await _purge(factory, wa, [])
        await engine.dispose()


async def test_retry_endpoint(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        token = await admin_csrf(client, settings)
        await _insert_lead(factory, wa)
        queued = await client.post(
            f"/api/chats/{wa}/messages", json={"body": "Повтор"}, headers=csrf_headers(token)
        )
        outbox_id = queued.json()["id"]
        async with factory() as session:
            await session.execute(
                text("UPDATE crm_outbox SET status = 'failed', attempts = 5 WHERE id = :id"),
                {"id": outbox_id},
            )
            await session.commit()

        retried = await client.post(
            f"/api/chats/outbox/{outbox_id}/retry", headers=csrf_headers(token)
        )
        assert retried.status_code == 200
        assert retried.json()["status"] == "queued"
        assert retried.json()["attempts"] == 0

        not_retryable = await client.post(
            f"/api/chats/outbox/{outbox_id}/retry", headers=csrf_headers(token)
        )
        assert not_retryable.status_code == 422
        missing = await client.post(
            "/api/chats/outbox/00000000-0000-0000-0000-000000000000/retry",
            headers=csrf_headers(token),
        )
        assert missing.status_code == 404
    finally:
        await _purge(factory, wa, [])
        await engine.dispose()


async def test_outbox_listing_and_quick_replies(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        token = await admin_csrf(client, settings)
        await _insert_lead(factory, wa)
        for text_body in ("Раз", "Два"):
            response = await client.post(
                f"/api/chats/{wa}/messages",
                json={"body": text_body},
                headers=csrf_headers(token),
            )
            assert response.status_code == 202
        listing = await client.get(f"/api/chats/{wa}/outbox?limit=10")
        assert listing.status_code == 200
        assert listing.json()["total"] == 2
        assert [item["body"] for item in listing.json()["items"]] == ["Два", "Раз"]

        replies = await client.get("/api/chats/quick-replies")
        assert replies.status_code == 200
        assert len(replies.json()["items"]) >= 3
    finally:
        await _purge(factory, wa, [])
        await engine.dispose()


class _MockN8nHandler(BaseHTTPRequestHandler):
    received: list[dict] = []
    response: dict = {"ok": True, "provider_message_id": "mock-pv-1"}
    status: int = 200

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).received.append(
            {
                "path": self.path,
                "secret": self.headers.get(N8N_SECRET_HEADER),
                "body": body,
            }
        )
        payload = json.dumps(type(self).response).encode()
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        pass


def _mock_server():
    _MockN8nHandler.received = []
    _MockN8nHandler.response = {"ok": True, "provider_message_id": "mock-pv-1"}
    _MockN8nHandler.status = 200
    server = HTTPServer(("127.0.0.1", 0), _MockN8nHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _sender_settings(server: HTTPServer) -> Settings:
    return Settings(
        SECRET_KEY="test-secret",
        N8N_SEND_WEBHOOK_URL=f"http://127.0.0.1:{server.server_port}/send",
        N8N_WEBHOOK_SECRET="s3cr3t",
    )


async def test_post_to_n8n_uses_mock_server():
    import asyncio

    server = _mock_server()
    try:
        settings = _sender_settings(server)
        payload = await post_to_n8n(
            settings,
            outbox_id=uuid.uuid4(),
            whatsapp_id="79990000001@c.us",
            text="Привет",
        )
        assert payload["provider_message_id"] == "mock-pv-1"
        await asyncio.to_thread(server.shutdown)
        assert len(_MockN8nHandler.received) == 1
        call = _MockN8nHandler.received[0]
        assert call["secret"] == "s3cr3t"
        assert call["body"]["whatsapp_id"] == "79990000001@c.us"
        assert call["body"]["text"] == "Привет"
        assert "outbox_id" in call["body"]
    finally:
        server.server_close()


async def test_post_to_n8n_rejects_failures():
    import asyncio

    server = _mock_server()
    try:
        settings = _sender_settings(server)
        _MockN8nHandler.response = {"ok": False, "error": "nope"}
        try:
            await post_to_n8n(settings, outbox_id=uuid.uuid4(), whatsapp_id="w", text="t")
        except N8nError:
            pass
        else:
            raise AssertionError("rejection must raise N8nError")
        finally:
            _MockN8nHandler.response = {"ok": True}

        _MockN8nHandler.status = 500
        try:
            await post_to_n8n(settings, outbox_id=uuid.uuid4(), whatsapp_id="w", text="t")
        except N8nError:
            pass
        else:
            raise AssertionError("HTTP 500 must raise N8nError")
        finally:
            _MockN8nHandler.status = 200
        await asyncio.to_thread(server.shutdown)
    finally:
        server.server_close()

    try:
        await post_to_n8n(
            Settings(SECRET_KEY="x"), outbox_id=uuid.uuid4(), whatsapp_id="w", text="t"
        )
    except OutboxConfigError:
        pass
    else:
        raise AssertionError("missing webhook config must raise OutboxConfigError")


async def test_manager_send_flow_end_to_end(client, app, settings):
    """Manager sends via API, mock n8n accepts, timeline shows the message."""
    from backend.tests.crm_helpers import ManagerSession

    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        token = await admin_csrf(client, settings)
        manager = await make_manager(client, token)
        await _insert_lead(factory, wa)
        await run_sync(factory)

        async with ManagerSession(app, manager["email"], manager["password"]) as mgr:
            assert mgr.client is not None
            queued = await mgr.client.post(
                f"/api/chats/{wa}/messages",
                json={"body": "Здравствуйте, Асель!"},
                headers=mgr.headers(),
            )
            assert queued.status_code == 202

        sender = _ok_sender(provider_id="e2e-pv")
        stats = await run_outbox_cycle(factory, settings, sender=sender)
        assert stats is not None and stats["sent"] == 1

        async with factory() as session:
            deal_id = (
                await session.execute(
                    text(
                        "SELECT d.id FROM crm_deals d JOIN crm_contacts c ON c.id = d.contact_id"
                        " WHERE c.whatsapp_id = :wa"
                    ),
                    {"wa": wa},
                )
            ).scalar_one()
        timeline = await client.get(f"/api/deals/{deal_id}/timeline?types=message&limit=50")
        assert timeline.status_code == 200
        manager_msgs = [
            item["data"]
            for item in timeline.json()["items"]
            if item["data"].get("message_type") == "manager"
        ]
        assert len(manager_msgs) == 1
        assert manager_msgs[0]["body"] == "Здравствуйте, Асель!"
        assert manager_msgs[0]["author_name"] == "Case Manager"
    finally:
        await _purge(factory, wa, [])
        await engine.dispose()
