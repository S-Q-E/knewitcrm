from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from backend.tests.conftest import csrf_headers, login, login_admin, unique_email
from backend.tests.crm_helpers import ManagerSession, engine_factory, make_manager

pytestmark = pytest.mark.usefixtures("db_available")

MANAGER_PASSWORD = "manager-password-1"


async def _manager_pair(client, app, admin_csrf: str):
    """Two separate logged-in sessions for the same manager (two devices)."""
    email = unique_email("devices")
    created = await client.post(
        "/api/users",
        json={"email": email, "name": "Two Devices", "password": MANAGER_PASSWORD},
        headers=csrf_headers(admin_csrf),
    )
    assert created.status_code == 201, created.text
    first = ManagerSession(app, email, MANAGER_PASSWORD)
    await first.__aenter__()
    second = ManagerSession(app, email, MANAGER_PASSWORD)
    await second.__aenter__()
    return first, second


async def test_settings_get_update_roundtrip(client, settings):
    admin = await login_admin(client, settings)
    headers = csrf_headers(admin["csrf"])

    initial = await client.get("/api/settings")
    assert initial.status_code == 200, initial.text
    assert initial.json() == {
        "restrict_managers_to_own": False,
        "auto_pause_on_manager": False,
        "auto_pause_on_manual_reply": True,
        "analytics_managers_visible": True,
        "deal_assignment_mode": "unassigned",
    }

    updated = await client.patch(
        "/api/settings",
        json={
            "restrict_managers_to_own": True,
            "auto_pause_on_manager": True,
            "auto_pause_on_manual_reply": False,
            "analytics_managers_visible": False,
            "deal_assignment_mode": "round_robin",
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    try:
        body = updated.json()
        assert body["restrict_managers_to_own"] is True
        assert body["deal_assignment_mode"] == "round_robin"

        partial = await client.patch(
            "/api/settings", json={"restrict_managers_to_own": False}, headers=headers
        )
        assert partial.status_code == 200
        assert partial.json()["restrict_managers_to_own"] is False
        # Untouched keys survive a partial update; round-robin keeps its index.
        assert partial.json()["deal_assignment_mode"] == "round_robin"

        engine, _ = engine_factory(settings)
        try:
            async with engine.connect() as conn:
                mode = (
                    await conn.execute(
                        text(
                            "SELECT value->>'mode' FROM crm_settings" " WHERE key='deal_assignment'"
                        )
                    )
                ).scalar_one()
                assert mode == "round_robin"
                logged = (
                    await conn.execute(
                        text(
                            "SELECT COUNT(*) FROM crm_activity_log"
                            " WHERE entity='settings' AND action='settings_updated'"
                        )
                    )
                ).scalar()
                assert logged and logged >= 2
        finally:
            await engine.dispose()
    finally:
        # Restore defaults so other tests see an open-access CRM.
        restored = await client.patch(
            "/api/settings",
            json={
                "restrict_managers_to_own": False,
                "auto_pause_on_manager": False,
                "auto_pause_on_manual_reply": True,
                "analytics_managers_visible": True,
                "deal_assignment_mode": "unassigned",
            },
            headers=headers,
        )
        assert restored.status_code == 200


async def test_settings_rejects_bad_mode_and_forbids_managers(client, settings, app):
    admin = await login_admin(client, settings)
    bad = await client.patch(
        "/api/settings",
        json={"deal_assignment_mode": "magic"},
        headers=csrf_headers(admin["csrf"]),
    )
    assert bad.status_code == 422

    manager = await make_manager(client, admin["csrf"])
    async with ManagerSession(app, manager["email"], manager["password"]) as mgr:
        assert mgr.client is not None
        denied = await mgr.client.get("/api/settings")
        assert denied.status_code == 403
        denied_patch = await mgr.client.patch(
            "/api/settings", json={"auto_pause_on_manager": True}, headers=mgr.headers()
        )
        assert denied_patch.status_code == 403
        assert (await mgr.client.get("/api/settings/integrations")).status_code == 403
        assert (await mgr.client.get("/api/activity")).status_code == 403


async def test_bot_stages_lists_real_values(client, settings):
    await login_admin(client, settings)
    response = await client.get("/api/settings/bot-stages")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "НОВЫЙ_ЛИД" in body["stages"]
    assert "ACTIVE" in body["statuses"]


async def test_quick_replies_crud(client, settings, app):
    admin = await login_admin(client, settings)
    headers = csrf_headers(admin["csrf"])
    title = f"tpl-{uuid.uuid4().hex[:8]}"

    created = await client.post(
        "/api/chats/quick-replies",
        json={"title": title, "body": "Hello {name}", "sort": 5},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    reply_id = created.json()["id"]

    duplicate = await client.post(
        "/api/chats/quick-replies",
        json={"title": title, "body": "Other"},
        headers=headers,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "QUICK_REPLY_EXISTS"

    listed = await client.get("/api/chats/quick-replies")
    assert any(item["id"] == reply_id for item in listed.json()["items"])

    patched = await client.patch(
        f"/api/chats/quick-replies/{reply_id}",
        json={"body": "Hi {name}!", "sort": 1},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["body"] == "Hi {name}!"

    manager = await make_manager(client, admin["csrf"])
    async with ManagerSession(app, manager["email"], manager["password"]) as mgr:
        assert mgr.client is not None
        assert (
            await mgr.client.post(
                "/api/chats/quick-replies",
                json={"title": f"m-{title}", "body": "x"},
                headers=mgr.headers(),
            )
        ).status_code == 403
        assert (
            await mgr.client.delete(f"/api/chats/quick-replies/{reply_id}", headers=mgr.headers())
        ).status_code == 403

    deleted = await client.delete(f"/api/chats/quick-replies/{reply_id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}
    missing = await client.delete(f"/api/chats/quick-replies/{reply_id}", headers=headers)
    assert missing.status_code == 404


async def test_sessions_list_and_revoke_others(client, settings, app):
    admin = await login_admin(client, settings)
    first, second = await _manager_pair(client, app, admin["csrf"])
    try:
        assert first.client is not None and second.client is not None
        listed = await first.client.get("/api/auth/sessions")
        assert listed.status_code == 200, listed.text
        items = listed.json()["items"]
        assert len(items) == 2
        assert sum(1 for item in items if item["is_current"]) == 1

        current_id = next(item["id"] for item in items if item["is_current"])
        own = await first.client.delete(f"/api/auth/sessions/{current_id}", headers=first.headers())
        assert own.status_code == 422
        assert own.json()["error"]["code"] == "CANNOT_REVOKE_CURRENT"

        revoked = await first.client.post(
            "/api/auth/sessions/revoke-others", headers=first.headers()
        )
        assert revoked.status_code == 200
        assert revoked.json()["revoked"] == 1

        # The other device session is dead now.
        stale = await second.client.get("/api/auth/me")
        assert stale.status_code == 401
        remaining = await first.client.get("/api/auth/sessions")
        assert len(remaining.json()["items"]) == 1
    finally:
        await first.__aexit__()
        await second.__aexit__()


async def test_profile_update_and_password_change(client, settings):
    admin = await login_admin(client, settings)
    created = await client.post(
        "/api/users",
        json={
            "email": unique_email("profile"),
            "name": "Old Name",
            "password": MANAGER_PASSWORD,
        },
        headers=csrf_headers(admin["csrf"]),
    )
    assert created.status_code == 201
    user = await login(client, created.json()["email"], MANAGER_PASSWORD)
    headers = csrf_headers(user["csrf"])

    renamed = await client.patch("/api/auth/profile", json={"name": "  New Name "}, headers=headers)
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "New Name"
    assert renamed.json()["email"] == created.json()["email"]

    changed = await client.post(
        "/api/auth/change-password",
        json={"current_password": MANAGER_PASSWORD, "new_password": "brand-new-password-1"},
        headers=headers,
    )
    assert changed.status_code == 200, changed.text


async def test_integrations_status_hides_secret(client, settings, app):
    admin = await login_admin(client, settings)
    response = await client.get("/api/settings/integrations")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["bot_db_ok"] is True
    assert body["bot_db_latency_ms"] is not None
    assert body["leads_count"] is not None
    assert "n8n_webhook_secret" not in response.text.lower()
    assert body["n8n_configured"] is False
    assert body["n8n_webhook_url"] is None
    for key in ("outbox_queued", "outbox_sending", "outbox_sent", "outbox_failed"):
        assert isinstance(body[key], int)

    manager = await make_manager(client, admin["csrf"])
    async with ManagerSession(app, manager["email"], manager["password"]) as mgr:
        assert mgr.client is not None
        assert (await mgr.client.get("/api/settings/integrations")).status_code == 403


async def test_outbox_journal_admin_only_with_status_filter(client, settings, app):
    admin = await login_admin(client, settings)
    journal = await client.get("/api/chats/outbox?status=failed&limit=5")
    assert journal.status_code == 200, journal.text
    body = journal.json()
    assert body["total"] >= 0
    assert all(item["status"] == "failed" for item in body["items"])

    bad_status = await client.get("/api/chats/outbox?status=bogus")
    assert bad_status.status_code == 422

    manager = await make_manager(client, admin["csrf"])
    async with ManagerSession(app, manager["email"], manager["password"]) as mgr:
        assert mgr.client is not None
        assert (await mgr.client.get("/api/chats/outbox")).status_code == 403


async def test_activity_journal_filters_and_pagination(client, settings, app):
    admin = await login_admin(client, settings)
    headers = csrf_headers(admin["csrf"])
    tag_name = f"audit-{uuid.uuid4().hex[:8]}"
    created = await client.post("/api/tags", json={"name": tag_name}, headers=headers)
    assert created.status_code == 201, created.text

    journal = await client.get("/api/activity?entity=tag&limit=5")
    assert journal.status_code == 200, journal.text
    body = journal.json()
    assert body["total"] >= 1
    assert all(item["entity"] == "tag" for item in body["items"])
    assert any(item["actor_name"] for item in body["items"])

    filtered = await client.get("/api/activity?action=tag_created&entity=tag&limit=5")
    assert filtered.status_code == 200
    assert filtered.json()["total"] >= 1

    far_future = await client.get("/api/activity?date_from=2999-01-01T00:00:00Z")
    assert far_future.status_code == 200
    assert far_future.json() == {"items": [], "total": 0}

    meta = await client.get("/api/activity/entities")
    assert meta.status_code == 200
    assert "tag" in meta.json()["entities"]

    manager = await make_manager(client, admin["csrf"])
    async with ManagerSession(app, manager["email"], manager["password"]) as mgr:
        assert mgr.client is not None
        assert (await mgr.client.get("/api/activity")).status_code == 403
