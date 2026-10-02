from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from backend.app.config import Settings
from backend.app.deps import get_settings
from backend.app.main import create_app
from backend.app.services.metrics import reset as reset_metrics
from backend.app.services.ratelimit import clear_all_limiters
from backend.app.workers.realtime_poller import _max_id
from backend.tests.conftest import csrf_headers, login, login_admin, unique_email
from backend.tests.crm_helpers import ManagerSession, admin_csrf, engine_factory, make_manager

pytestmark = pytest.mark.usefixtures("db_available")

MANAGER_PASSWORD = "manager-password-1"


def _custom_settings(**overrides) -> Settings:
    base = {
        "cookie_secure": False,
        "sync_enabled": False,
        "outbox_enabled": False,
        "notifications_enabled": False,
        "realtime_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)


async def _custom_client(settings: Settings):
    """Standalone app with custom Settings (fresh middleware state)."""
    application = create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    lifespan = LifespanManager(application)
    await lifespan.__aenter__()
    ac = AsyncClient(transport=ASGITransport(app=application), base_url="http://test")
    await ac.__aenter__()
    return lifespan, ac


async def _close(lifespan, ac) -> None:
    await ac.__aexit__()
    await lifespan.__aexit__()


async def _audit_count(factory, action: str) -> int:
    async with factory() as session:
        return (
            await session.execute(
                text("SELECT COUNT(*) FROM crm_activity_log WHERE action = :action"),
                {"action": action},
            )
        ).scalar() or 0


async def test_security_headers_on_api_and_spa(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    headers = response.headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "max-age=31536000" in headers["strict-transport-security"]
    csp = headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    script_src = csp.split("script-src")[1].split(";")[0]
    assert "unsafe-inline" not in script_src

    spa = await client.get("/deals")
    assert spa.status_code == 200
    assert spa.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" in spa.headers


async def test_cors_only_from_allowed_origins(settings):
    allowed = _custom_settings(allowed_origins=["https://crm.example.com"])
    lifespan, ac = await _custom_client(allowed)
    try:
        preflight = await ac.options(
            "/api/health",
            headers={
                "Origin": "https://crm.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "https://crm.example.com"
        evil = await ac.options(
            "/api/health",
            headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"},
        )
        assert "access-control-allow-origin" not in evil.headers
    finally:
        await _close(lifespan, ac)


async def test_api_rate_limit_429_with_retry_after(settings):
    limited = _custom_settings(rate_limit_per_minute=3)
    lifespan, ac = await _custom_client(limited)
    try:
        codes = []
        for _ in range(6):
            response = await ac.get("/api/health")
            codes.append(response.status_code)
        assert codes[:3] == [200, 200, 200]
        assert codes[3] == 429
        denied = await ac.get("/api/health")
        assert denied.status_code == 429
        assert denied.json()["error"]["code"] == "RATE_LIMITED"
        assert "retry-after" in denied.headers
    finally:
        await _close(lifespan, ac)


async def test_send_rate_limit_per_user(client, settings):
    admin = await login_admin(client, settings)
    headers = csrf_headers(admin["csrf"])
    try:
        statuses = []
        for _ in range(35):
            response = await client.post(
                "/api/chats/unknown-wa/messages", json={"body": "probe"}, headers=headers
            )
            statuses.append(response.status_code)
        # Default budget is 30/min: early hits 404 (no lead), later hits 429.
        assert 404 in statuses
        assert 429 in statuses
        assert response.json()["error"]["code"] == "RATE_LIMITED"
    finally:
        clear_all_limiters()


async def test_body_limit_413(settings):
    tiny = _custom_settings(max_request_body_bytes=1024)
    lifespan, ac = await _custom_client(tiny)
    try:
        big = await ac.post("/api/auth/login", json={"email": "x" * 2000, "password": "y"})
        assert big.status_code == 413
        assert big.json()["error"]["code"] == "REQUEST_TOO_LARGE"
        small = await ac.post("/api/auth/login", json={"email": "a", "password": "b"})
        assert small.status_code in (401, 422)
    finally:
        await _close(lifespan, ac)


async def test_metrics_disabled_404_and_token_gate(client, settings):
    # Anonymous callers always get the uniform 401 from session auth.
    assert (await client.get("/api/metrics")).status_code == 401
    # Authenticated, but no token configured -> 404 so scanners learn nothing.
    await login_admin(client, settings)
    missing = await client.get("/api/metrics")
    assert missing.status_code == 404

    guarded = _custom_settings(metrics_token="secret-token")
    lifespan, ac = await _custom_client(guarded)
    try:
        await login_admin(ac, settings)
        assert (await ac.get("/api/metrics")).status_code == 403
        wrong = await ac.get("/api/metrics", headers={"Authorization": "Bearer wrong"})
        assert wrong.status_code == 403
        ok_response = await ac.get("/api/metrics", headers={"Authorization": "Bearer secret-token"})
        assert ok_response.status_code == 200
        assert "crm_http_requests_total" in ok_response.text
        assert "crm_uptime_seconds" in ok_response.text
        reset_metrics()
    finally:
        await _close(lifespan, ac)


async def test_password_change_rotates_session(client, settings, app):
    admin = await login_admin(client, settings)
    created = await client.post(
        "/api/users",
        json={
            "email": unique_email("rotate"),
            "name": "Rotate Me",
            "password": MANAGER_PASSWORD,
        },
        headers=csrf_headers(admin["csrf"]),
    )
    assert created.status_code == 201
    email = created.json()["email"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as first:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as second:
            first_auth = await login(first, email, MANAGER_PASSWORD)
            await login(second, email, MANAGER_PASSWORD)
            old_cookie = first.cookies.get("crm_session")
            assert old_cookie

            changed = await first.post(
                "/api/auth/change-password",
                json={"current_password": MANAGER_PASSWORD, "new_password": "rotated-password-1"},
                headers=csrf_headers(first_auth["csrf"]),
            )
            assert changed.status_code == 200, changed.text
            # Transparent rotation: this jar got fresh cookies and keeps working.
            assert first.cookies.get("crm_session") != old_cookie
            assert (await first.get("/api/auth/me")).status_code == 200
            # The old token is dead, and so is the other device.
            assert (await second.get("/api/auth/me")).status_code == 401
            stale = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
            stale.cookies.set("crm_session", old_cookie)
            assert (await stale.get("/api/auth/me")).status_code == 401


async def test_audit_login_user_export(client, settings):
    engine, factory = engine_factory(settings)
    user_id: str | None = None
    try:
        before_login = await _audit_count(factory, "auth_login")
        admin = await login_admin(client, settings)
        assert await _audit_count(factory, "auth_login") == before_login + 1

        headers = csrf_headers(admin["csrf"])
        before_users = await _audit_count(factory, "user_created")
        created = await client.post(
            "/api/users",
            json={
                "email": unique_email("audited"),
                "name": "Audited",
                "password": MANAGER_PASSWORD,
            },
            headers=headers,
        )
        assert created.status_code == 201
        assert await _audit_count(factory, "user_created") == before_users + 1

        user_id = created.json()["id"]
        patched = await client.patch(
            f"/api/users/{user_id}", json={"role": "admin"}, headers=headers
        )
        assert patched.status_code == 200
        async with factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT diff FROM crm_activity_log WHERE action = 'user_updated'"
                        " ORDER BY created_at DESC LIMIT 1"
                    )
                )
            ).scalar_one()
            assert row["changed"]["role"] == {"old": "manager", "new": "admin"}

        before_export = await _audit_count(factory, "contacts_export")
        exported = await client.get("/api/contacts/export?format=csv")
        assert exported.status_code == 200
        assert await _audit_count(factory, "contacts_export") == before_export + 1
    finally:
        # Never leave extra admins behind: the LAST_ADMIN guard only protects
        # the bootstrap admin while it is the *only* admin.
        if user_id is not None:
            admin = await login_admin(client, settings)
            await client.patch(
                f"/api/users/{user_id}",
                json={"role": "manager", "is_active": True},
                headers=csrf_headers(admin["csrf"]),
            )
        await engine.dispose()


async def test_audit_import_finished(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        csv_text = "full_name,phone_number\nИмпорт,+77019998877\n"
        mapping = {"full_name": "name", "phone_number": "phone"}
        job_resp = await client.post(
            "/api/contacts/import",
            files={"file": ("contacts.csv", csv_text.encode(), "text/csv")},
            data={"mapping": json.dumps(mapping)},
            headers=csrf_headers(token),
        )
        assert job_resp.status_code == 201, job_resp.text
        job_id = job_resp.json()["id"]
        for _ in range(100):
            status = await client.get(f"/api/contacts/import/{job_id}")
            if status.json()["status"] == "done":
                break
            await asyncio.sleep(0.05)
        assert (await client.get(f"/api/contacts/import/{job_id}")).json()["status"] == "done"
        assert await _audit_count(factory, "import_finished") >= 1
        found = await client.get("/api/contacts?search=%2B77019998877")
        for item in found.json()["items"]:
            contact_ids.append(item["id"])
    finally:
        from backend.tests.crm_helpers import purge_contacts

        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_malicious_message_content_round_trips_as_text(client, settings):
    engine, factory = engine_factory(settings)
    wa = f"7999{uuid.uuid4().hex[:8]}@c.us"
    token = await admin_csrf(client, settings)
    payload = "<script>alert('xss')</script>' OR '1'='1'; --"
    try:
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO knewit_leads (whatsapp_id, name, current_stage, status)"
                    " VALUES (:wa, 'XSS Probe', 'НОВЫЙ_ЛИД', 'ACTIVE')"
                ),
                {"wa": wa},
            )
            await session.commit()
        sent = await client.post(
            f"/api/chats/{wa}/messages", json={"body": payload}, headers=csrf_headers(token)
        )
        assert sent.status_code == 202, sent.text
        listed = await client.get(f"/api/chats/{wa}/outbox?limit=5")
        assert listed.status_code == 200
        assert listed.json()["items"][0]["body"] == payload
        # JSON transport, never HTML: browsers cannot execute the content.
        assert listed.headers["content-type"].startswith("application/json")
    finally:
        async with factory() as session:
            await session.execute(
                text("DELETE FROM crm_outbox WHERE whatsapp_id = :wa"), {"wa": wa}
            )
            await session.execute(
                text("DELETE FROM knewit_leads WHERE whatsapp_id = :wa"), {"wa": wa}
            )
            await session.commit()
        await engine.dispose()


async def test_poller_rejects_unexpected_tables(tx_session):
    with pytest.raises(ValueError, match="unexpected table"):
        await _max_id(tx_session, "crm_users")


async def test_pool_defaults(settings):
    assert settings.db_pool_size == 5
    assert settings.db_pool_max_overflow == 5
    assert settings.db_pool_timeout == 30
    assert settings.rate_limit_per_minute == 600
    assert settings.rate_limit_send_per_minute == 30
    assert settings.max_request_body_bytes == 10 * 1024 * 1024
    assert settings.metrics_token == ""
    assert settings.shutdown_timeout_seconds == 10


async def test_sentry_init_is_opt_in(settings):
    from backend.app.services.sentry import init_sentry

    assert init_sentry(settings) is False
    assert init_sentry(_custom_settings(sentry_dsn="https://x@y/1")) is True


async def test_manager_cannot_touch_metrics_or_admin_settings(client, settings, app):
    admin = await login_admin(client, settings)
    manager = await make_manager(client, admin["csrf"])
    async with ManagerSession(app, manager["email"], manager["password"]) as mgr:
        assert mgr.client is not None
        assert (await mgr.client.get("/api/metrics")).status_code in (403, 404)
        assert (await mgr.client.get("/api/settings")).status_code == 403
