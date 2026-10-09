from __future__ import annotations

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from backend.tests.conftest import csrf_headers, login, login_admin, unique_email

pytestmark = pytest.mark.usefixtures("db_available")

MANAGER_PASSWORD = "manager-password-1"


async def _create_user(client, csrf: str, **overrides) -> dict:
    payload = {
        "email": unique_email("manager"),
        "name": "Test Manager",
        "password": MANAGER_PASSWORD,
        "role": "manager",
    }
    payload.update(overrides)
    response = await client.post("/api/users", json=payload, headers=csrf_headers(csrf))
    assert response.status_code == 201, response.text
    return response.json()


async def _manager_client(app, email: str, password: str):
    """A second logged-in client (separate cookie jar) for the same app."""
    async with LifespanManager(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as manager_http:
            csrf = (await login(manager_http, email, password))["csrf"]
            yield manager_http, csrf


async def test_admin_creates_manager(client, settings):
    admin = await login_admin(client, settings)
    created = await _create_user(client, admin["csrf"])
    assert created["email"].startswith("manager-")
    assert created["role"] == "manager"
    assert created["is_active"] is True
    assert "password_hash" not in created


async def test_create_user_validates_password_length(client, settings):
    admin = await login_admin(client, settings)
    response = await client.post(
        "/api/users",
        json={"email": unique_email("weak"), "name": "Weak", "password": "short"},
        headers=csrf_headers(admin["csrf"]),
    )
    assert response.status_code == 422


async def test_duplicate_email_conflict(client, settings):
    admin = await login_admin(client, settings)
    email = unique_email("dup")
    await _create_user(client, admin["csrf"], email=email)
    again = await client.post(
        "/api/users",
        json={"email": email, "name": "Dup", "password": MANAGER_PASSWORD},
        headers=csrf_headers(admin["csrf"]),
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "EMAIL_TAKEN"


async def test_admin_list_pagination(client, settings):
    admin = await login_admin(client, settings)
    await _create_user(client, admin["csrf"])
    first = await client.get("/api/users?limit=1&offset=0")
    assert first.status_code == 200
    body = first.json()
    assert len(body["items"]) == 1
    assert body["total"] >= 2
    assert set(body["items"][0]) >= {"id", "email", "name", "role", "is_active"}


async def test_manager_gets_lite_list_only(client, settings, app):
    admin = await login_admin(client, settings)
    created = await _create_user(client, admin["csrf"])
    async for manager_http, _ in _manager_client(app, created["email"], MANAGER_PASSWORD):
        response = await manager_http.get("/api/users")
        assert response.status_code == 200
        body = response.json()
        assert body["items"]
        assert all(set(item) == {"id", "name"} for item in body["items"])
        assert any(item["id"] == created["id"] for item in body["items"])


async def test_manager_forbidden_on_admin_endpoints(client, settings, app):
    admin = await login_admin(client, settings)
    created = await _create_user(client, admin["csrf"])
    async for manager_http, csrf in _manager_client(app, created["email"], MANAGER_PASSWORD):
        forbidden_post = await manager_http.post(
            "/api/users",
            json={"email": unique_email("x"), "name": "X", "password": MANAGER_PASSWORD},
            headers=csrf_headers(csrf),
        )
        assert forbidden_post.status_code == 403

        forbidden_get = await manager_http.get(f"/api/users/{created['id']}")
        assert forbidden_get.status_code == 403

        forbidden_patch = await manager_http.patch(
            f"/api/users/{created['id']}",
            json={"name": "Hacked"},
            headers=csrf_headers(csrf),
        )
        assert forbidden_patch.status_code == 403


async def test_deactivation_revokes_sessions(client, settings, app):
    admin = await login_admin(client, settings)
    created = await _create_user(client, admin["csrf"])
    async for manager_http, csrf in _manager_client(app, created["email"], MANAGER_PASSWORD):
        assert (await manager_http.get("/api/auth/me")).status_code == 200
        deactivated = await client.patch(
            f"/api/users/{created['id']}",
            json={"is_active": False},
            headers=csrf_headers(admin["csrf"]),
        )
        assert deactivated.status_code == 200
        assert deactivated.json()["is_active"] is False
        # Old session cookie no longer works; login is refused as well.
        assert (await manager_http.get("/api/auth/me")).status_code == 401
        relogin = await manager_http.post(
            "/api/auth/login",
            json={"email": created["email"], "password": MANAGER_PASSWORD},
        )
        assert relogin.status_code == 401
        assert csrf  # CSRF token itself was valid before deactivation


async def test_admin_password_reset(client, settings, app):
    admin = await login_admin(client, settings)
    created = await _create_user(client, admin["csrf"])
    reset = await client.patch(
        f"/api/users/{created['id']}",
        json={"password": "reset-password-9"},
        headers=csrf_headers(admin["csrf"]),
    )
    assert reset.status_code == 200
    async for manager_http, _ in _manager_client(app, created["email"], "reset-password-9"):
        assert (await manager_http.get("/api/auth/me")).status_code == 200


async def test_last_admin_is_protected(client, settings):
    admin = await login_admin(client, settings)
    admin_id = admin["user"]["id"]
    deactivate = await client.patch(
        f"/api/users/{admin_id}",
        json={"is_active": False},
        headers=csrf_headers(admin["csrf"]),
    )
    assert deactivate.status_code == 409
    assert deactivate.json()["error"]["code"] == "LAST_ADMIN"

    demote = await client.patch(
        f"/api/users/{admin_id}",
        json={"role": "manager"},
        headers=csrf_headers(admin["csrf"]),
    )
    assert demote.status_code == 409


async def test_users_require_session(client):
    assert (await client.get("/api/users")).status_code == 401
    assert (await client.post("/api/users", json={})).status_code == 401


async def test_get_missing_user_is_404(client, settings):
    await login_admin(client, settings)
    response = await client.get("/api/users/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_admin_password_reset_revokes_the_users_sessions(client, settings, app):
    admin = await login_admin(client, settings)
    created = await _create_user(client, admin["csrf"])
    async for manager_http, _ in _manager_client(app, created["email"], MANAGER_PASSWORD):
        assert (await manager_http.get("/api/auth/me")).status_code == 200
        reset = await client.patch(
            f"/api/users/{created['id']}",
            json={"password": "reset-password-9"},
            headers=csrf_headers(admin["csrf"]),
        )
        assert reset.status_code == 200
        assert (await manager_http.get("/api/auth/me")).status_code == 401


async def test_admin_changing_own_password_keeps_only_current_session(client, settings, app):
    admin = await login_admin(client, settings)
    me = (await client.get("/api/auth/me")).json()
    headers = csrf_headers(admin["csrf"])
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
            await login(other, settings.admin_email, settings.admin_password)
            assert (await other.get("/api/auth/me")).status_code == 200
            changed = await client.patch(
                f"/api/users/{me['id']}",
                json={"password": "admin-rotated-pass-1"},
                headers=headers,
            )
            assert changed.status_code == 200, changed.text
            assert (await other.get("/api/auth/me")).status_code == 401
            assert (await client.get("/api/auth/me")).status_code == 200
    restored = await client.patch(
        f"/api/users/{me['id']}",
        json={"password": settings.admin_password},
        headers=headers,
    )
    assert restored.status_code == 200, restored.text
