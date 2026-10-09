from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from backend.tests.crm_helpers import (
    ManagerSession,
    admin_csrf,
    engine_factory,
    make_manager,
    purge_contacts,
    run_sync,
)

pytestmark = pytest.mark.usefixtures("db_available")


def _wa() -> str:
    return f"7999{uuid.uuid4().hex[:8]}@c.us"


async def _insert_lead(factory, wa: str, status: str = "ACTIVE") -> None:
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO knewit_leads (whatsapp_id, name, current_stage, status)"
                " VALUES (:wa, 'Notify Bot', 'НОВЫЙ_ЛИД', :status)"
            ),
            {"wa": wa, "status": status},
        )
        await session.commit()


async def _purge_lead(factory, wa: str) -> None:
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


async def _notifications(factory, email: str) -> list[dict]:
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT n.type, n.read_at IS NOT NULL AS read, n.payload"
                        " FROM crm_notifications n JOIN crm_users u ON u.id = n.user_id"
                        " WHERE u.email = :email ORDER BY n.created_at"
                    ),
                    {"email": email},
                )
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows]


async def test_handover_creates_task_and_notification(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        token = await admin_csrf(client, settings)
        owner = await make_manager(client, token)
        await _insert_lead(factory, wa, "МЕНЕДЖЕР")
        await run_sync(factory)
        deal_id = await _deal_id(factory, wa)

        async with factory() as session:
            tasks = (
                (
                    await session.execute(
                        text(
                            "SELECT title, assignee_id FROM crm_tasks WHERE deal_id = :id"
                            " AND done_at IS NULL"
                        ),
                        {"id": deal_id},
                    )
                )
                .mappings()
                .all()
            )
            assert [t["title"] for t in tasks] == ["Ответить клиенту"]
            assert tasks[0]["assignee_id"] is None
            paused = (
                await session.execute(
                    text("SELECT bot_paused FROM crm_conversation_state WHERE whatsapp_id = :wa"),
                    {"wa": wa},
                )
            ).scalar()
            assert paused is False

        notes = await _notifications(factory, owner["email"])
        handovers = [
            n
            for n in notes
            if n["type"] == "manager_handover"
            and (n["payload"] or {}).get("deal_id") == str(deal_id)
        ]
        assert len(handovers) == 1 and not handovers[0]["read"]

        # Idempotent: rerun creates no duplicate task or notification.
        await run_sync(factory)
        async with factory() as session:
            count = (
                await session.execute(
                    text("SELECT COUNT(*) FROM crm_tasks WHERE deal_id = :id"), {"id": deal_id}
                )
            ).scalar()
            assert count == 1
        notes = await _notifications(factory, owner["email"])
        handovers = [
            n
            for n in notes
            if n["type"] == "manager_handover"
            and (n["payload"] or {}).get("deal_id") == str(deal_id)
        ]
        assert len(handovers) == 1
    finally:
        await _purge_lead(factory, wa)
        await engine.dispose()


async def _deal_id(factory, wa: str):
    async with factory() as session:
        return (
            await session.execute(
                text(
                    "SELECT d.id FROM crm_deals d JOIN crm_contacts c ON c.id = d.contact_id"
                    " WHERE c.whatsapp_id = :wa"
                ),
                {"wa": wa},
            )
        ).scalar_one()


async def test_handover_once_per_deal_after_task_done_and_read(client, settings):
    from backend.app.workers.sync_worker import run_sync_cycle

    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        token = await admin_csrf(client, settings)
        owner = await make_manager(client, token)
        await _insert_lead(factory, wa, "МЕНЕДЖЕР")
        await run_sync(factory)
        deal_id = await _deal_id(factory, wa)
        async with factory() as session:
            await session.execute(
                text("UPDATE crm_tasks SET done_at = now() WHERE deal_id = :id"), {"id": deal_id}
            )
            await session.execute(
                text(
                    "UPDATE crm_notifications SET read_at = now()"
                    " WHERE type = 'manager_handover' AND payload->>'deal_id' = :id"
                ),
                {"id": str(deal_id)},
            )
            await session.commit()

        await run_sync(factory)
        await run_sync_cycle(factory, force_full=True)

        async with factory() as session:
            task_count = (
                await session.execute(
                    text("SELECT COUNT(*) FROM crm_tasks WHERE deal_id = :id"), {"id": deal_id}
                )
            ).scalar_one()
            per_user = (
                (
                    await session.execute(
                        text(
                            "SELECT user_id, COUNT(*) AS n FROM crm_notifications"
                            " WHERE type = 'manager_handover' AND payload->>'deal_id' = :id"
                            " GROUP BY user_id"
                        ),
                        {"id": str(deal_id)},
                    )
                )
                .mappings()
                .all()
            )
        assert task_count == 1
        assert per_user and all(row["n"] == 1 for row in per_user)
        assert str(owner["user"]["id"]) in {str(row["user_id"]) for row in per_user}
    finally:
        await _purge_lead(factory, wa)
        await engine.dispose()


async def test_autopause_opt_in(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        await admin_csrf(client, settings)
        await _insert_lead(factory, wa, "МЕНЕДЖЕР")
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO crm_settings (key, value) VALUES"
                    " ('auto_pause_on_manager', 'true')"
                    " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
                )
            )
            await session.commit()
        try:
            await run_sync(factory)
            async with factory() as session:
                paused = (
                    await session.execute(
                        text(
                            "SELECT bot_paused FROM crm_conversation_state WHERE whatsapp_id = :wa"
                        ),
                        {"wa": wa},
                    )
                ).scalar()
                assert paused is True
        finally:
            async with factory() as session:
                await session.execute(
                    text("DELETE FROM crm_settings WHERE key = 'auto_pause_on_manager'")
                )
                await session.commit()
    finally:
        await _purge_lead(factory, wa)
        await engine.dispose()


async def test_locked_stage_notifies_owner(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        token = await admin_csrf(client, settings)
        owner = await make_manager(client, token)
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
            await session.execute(
                text("UPDATE crm_deals SET stage_locked = TRUE, owner_id = :owner WHERE id = :id"),
                {"owner": owner["user"]["id"], "id": deal_id},
            )
            await session.execute(
                text(
                    "UPDATE knewit_leads SET current_stage = 'ЗАПИСЬ', updated_at = now()"
                    " WHERE whatsapp_id = :wa"
                ),
                {"wa": wa},
            )
            await session.commit()
        await run_sync(factory)
        notes = await _notifications(factory, owner["email"])
        assert any(n["type"] == "locked_stage" and not n["read"] for n in notes)
    finally:
        await _purge_lead(factory, wa)
        await engine.dispose()


async def test_notification_endpoints(client, settings, app):
    token = await admin_csrf(client, settings)
    manager = await make_manager(client, token)
    async with ManagerSession(app, manager["email"], manager["password"]) as mgr:
        assert mgr.client is not None
        engine, factory = engine_factory(settings)
        try:
            from backend.app.services.notifications import notify

            async with factory() as session:
                await notify(
                    session,
                    [manager["user"]["id"]],
                    "deal_assigned",
                    {"deal_id": "x"},
                )
                await session.commit()

            listed = await mgr.client.get("/api/notifications")
            assert listed.status_code == 200
            body = listed.json()
            assert body["total"] == 1
            assert body["unread_total"] == 1
            note_id = body["items"][0]["id"]

            read = await mgr.client.post(
                f"/api/notifications/{note_id}/read", headers=mgr.headers()
            )
            assert read.json() == {"ok": True}
            remaining = await mgr.client.get("/api/notifications?unread_only=true")
            assert remaining.json()["total"] == 0

            read_all = await mgr.client.post("/api/notifications/read-all", headers=mgr.headers())
            assert read_all.json()["marked"] == 0

            missing = await mgr.client.post(
                "/api/notifications/00000000-0000-0000-0000-000000000000/read",
                headers=mgr.headers(),
            )
            assert missing.status_code == 404
        finally:
            async with factory() as session:
                await session.execute(text("DELETE FROM crm_notifications"))
                await session.commit()
            await engine.dispose()
