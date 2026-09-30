from __future__ import annotations

import pytest
from sqlalchemy import delete, text

from backend.app.models import CrmUser
from backend.app.services.bootstrap import ensure_bootstrap_admin
from backend.tests.conftest import csrf_headers, login, login_admin, unique_email

pytestmark = pytest.mark.usefixtures("db_available")

MANAGER_PASSWORD = "manager-password-1"


async def _make_manager(client, settings, email: str | None = None) -> dict:
    admin = await login_admin(client, settings)
    email = email or unique_email("manager")
    response = await client.post(
        "/api/users",
        json={
            "email": email,
            "name": "Test Manager",
            "password": MANAGER_PASSWORD,
            "role": "manager",
        },
        headers=csrf_headers(admin["csrf"]),
    )
    assert response.status_code == 201, response.text
    return {"email": email, "user": response.json()}


async def test_login_logout_flow(client, settings):
    await login_admin(client, settings)

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == settings.admin_email
    assert me.json()["role"] == "admin"

    assert client.cookies.get("crm_session")
    csrf = client.cookies.get("crm_csrf")
    assert csrf

    logout = await client.post("/api/auth/logout", headers=csrf_headers(csrf))
    assert logout.status_code == 200
    assert logout.json() == {"ok": True}

    after = await client.get("/api/auth/me")
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "UNAUTHORIZED"


async def test_session_cookie_is_httponly(client, settings):
    admin = await login_admin(client, settings)
    assert admin["user"]["email"] == settings.admin_email
    # httpx jar hides flags; check the raw Set-Cookie header instead.
    response = await client.post(
        "/api/auth/login",
        json={"email": settings.admin_email, "password": settings.admin_password},
    )
    assert response.status_code == 200
    set_cookie = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in set_cookie if c.startswith("crm_session="))
    assert "HttpOnly" in session_cookie
    assert "SameSite=lax" in session_cookie
    csrf_cookie = next(c for c in set_cookie if c.startswith("crm_csrf="))
    assert "HttpOnly" not in csrf_cookie


async def test_session_cookie_flags_follow_settings(settings):
    from fastapi import Response

    from backend.app.config import Settings
    from backend.app.cookies import set_session_cookies

    secure_response = Response()
    set_session_cookies(secure_response, Settings(cookie_secure=True), "t" * 64, "csrf")
    secure_header = next(
        c for c in secure_response.headers.getlist("set-cookie") if c.startswith("crm_session=")
    )
    assert "Secure" in secure_header

    plain_response = Response()
    set_session_cookies(plain_response, settings, "t" * 64, "csrf")
    plain_header = next(
        c for c in plain_response.headers.getlist("set-cookie") if c.startswith("crm_session=")
    )
    assert "Secure" not in plain_header


async def test_me_without_session_is_unauthorized(client):
    response = await client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_login_invalid_credentials(client):
    response = await client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "wrong-password-1"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_login_rate_limited_after_five_failures(client):
    email = unique_email("ratelimit")
    for _ in range(5):
        response = await client.post(
            "/api/auth/login", json={"email": email, "password": "wrong-password-1"}
        )
        assert response.status_code == 401
    blocked = await client.post(
        "/api/auth/login", json={"email": email, "password": "wrong-password-1"}
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"


def _fake_ip(xff: str | None, peer: str = "peer-ip", hops: int | None = 1) -> str:
    from starlette.requests import Request

    from backend.app.session_middleware import client_ip

    headers = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode("utf-8")))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/login",
        "headers": headers,
        "client": (peer, 5000),
    }
    return client_ip(Request(scope), trusted_proxy_hops=hops)


def test_client_ip_trust_levels():
    # One trusted proxy (default): the last value is proxy-added, a spoofed
    # prefix to its left is ignored.
    assert _fake_ip("spoofed, real", hops=1) == "real"
    assert _fake_ip("only", hops=1) == "only"
    assert _fake_ip(None, hops=1) == "peer-ip"
    assert _fake_ip("", hops=1) == "peer-ip"
    # Two trusted proxies: second value from the right.
    assert _fake_ip("client, inner-peer, outer-peer", hops=2) == "inner-peer"
    # Chain shorter than the trusted hops: nothing trustworthy, use the peer.
    assert _fake_ip("lonely", hops=2) == "peer-ip"
    assert _fake_ip(None, hops=2) == "peer-ip"
    # No proxy in front: the header is attacker-controlled, always the peer.
    assert _fake_ip("spoofed, real", hops=0) == "peer-ip"
    assert _fake_ip(None, hops=0) == "peer-ip"


async def test_login_rate_limit_uses_last_forwarded_ip(client):
    """A spoofed XFF prefix must not shift the block onto another key."""
    email = unique_email("spoof")
    payload = {"email": email, "password": "wrong-password-1"}
    headers = {"X-Forwarded-For": "10.0.0.1, 10.0.0.2"}
    for _ in range(5):
        response = await client.post("/api/auth/login", json=payload, headers=headers)
        assert response.status_code == 401
    blocked = await client.post("/api/auth/login", json=payload, headers=headers)
    assert blocked.status_code == 429

    # Same last IP on its own is still blocked: the last value was keyed.
    same_last = await client.post(
        "/api/auth/login", json=payload, headers={"X-Forwarded-For": "10.0.0.2"}
    )
    assert same_last.status_code == 429
    # The spoofed first value on its own is not blocked: it was never keyed.
    spoofed_first = await client.post(
        "/api/auth/login", json=payload, headers={"X-Forwarded-For": "10.0.0.1"}
    )
    assert spoofed_first.status_code == 401


async def test_login_rate_limited_per_email_across_ips(client):
    """Rotating IPs must not bypass the per-email failure budget."""
    email = unique_email("emailflood")
    payload = {"email": email, "password": "wrong-password-1"}
    for i in range(20):
        response = await client.post(
            "/api/auth/login", json=payload, headers={"X-Forwarded-For": f"10.1.0.{i}"}
        )
        assert response.status_code == 401, i
    fresh_ip = await client.post(
        "/api/auth/login", json=payload, headers={"X-Forwarded-For": "10.9.9.9"}
    )
    assert fresh_ip.status_code == 429
    assert fresh_ip.json()["error"]["code"] == "RATE_LIMITED"
    # The block is email-scoped: another email from the same IP still passes.
    other = await client.post(
        "/api/auth/login",
        json={"email": unique_email("other"), "password": "wrong-password-1"},
        headers={"X-Forwarded-For": "10.9.9.9"},
    )
    assert other.status_code == 401


async def test_csrf_required_for_unsafe_methods(client, settings):
    await login_admin(client, settings)
    no_header = await client.post("/api/auth/logout")
    assert no_header.status_code == 403
    assert no_header.json()["error"]["code"] == "CSRF_REQUIRED"

    bad_header = await client.post("/api/auth/logout", headers={"X-CSRF-Token": "bogus"})
    assert bad_header.status_code == 403
    assert bad_header.json()["error"]["code"] == "CSRF_MISMATCH"


async def test_login_is_exempt_from_csrf(client, settings):
    # No cookies/headers at all: login must still work.
    response = await client.post(
        "/api/auth/login",
        json={"email": settings.admin_email, "password": settings.admin_password},
    )
    assert response.status_code == 200


async def test_change_password(client, settings):
    created = await _make_manager(client, settings)
    auth = await login(client, created["email"], MANAGER_PASSWORD)

    wrong = await client.post(
        "/api/auth/change-password",
        json={"current_password": "not-the-password-1", "new_password": "new-password-22"},
        headers=csrf_headers(auth["csrf"]),
    )
    assert wrong.status_code == 400

    weak = await client.post(
        "/api/auth/change-password",
        json={"current_password": MANAGER_PASSWORD, "new_password": "short"},
        headers=csrf_headers(auth["csrf"]),
    )
    assert weak.status_code == 422

    ok = await client.post(
        "/api/auth/change-password",
        json={"current_password": MANAGER_PASSWORD, "new_password": "new-password-22"},
        headers=csrf_headers(auth["csrf"]),
    )
    assert ok.status_code == 200

    stale = await client.post(
        "/api/auth/login", json={"email": created["email"], "password": MANAGER_PASSWORD}
    )
    assert stale.status_code == 401
    await login(client, created["email"], "new-password-22")


async def test_bootstrap_creates_first_admin_only(tx_session):
    await tx_session.execute(delete(CrmUser))
    created = await ensure_bootstrap_admin(tx_session, "first@example.com", "first-password-1")
    assert created is True

    skipped = await ensure_bootstrap_admin(tx_session, "second@example.com", "second-password-2")
    assert skipped is False
    assert tx_session is not None


async def test_bootstrap_rejects_short_password(tx_session):
    await tx_session.execute(delete(CrmUser))
    try:
        await ensure_bootstrap_admin(tx_session, "x@example.com", "short")
    except ValueError:
        pass
    else:
        raise AssertionError("short ADMIN_PASSWORD must raise ValueError")
    count = (await tx_session.execute(text("SELECT COUNT(*) FROM crm_users"))).scalar()
    assert count == 0
