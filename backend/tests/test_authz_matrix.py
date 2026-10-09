from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from backend.tests.conftest import login_admin
from backend.tests.crm_helpers import ManagerSession, make_manager

pytestmark = pytest.mark.usefixtures("db_available")

DUMMY_UUID = "00000000-0000-0000-0000-000000000000"

# Routes intentionally reachable without a session.
PUBLIC = {
    ("GET", "/api/health"),
    ("GET", "/api/ready"),
    ("POST", "/api/auth/login"),
    # Scrapers send only a Bearer token; the route itself enforces it (test_hardening).
    ("GET", "/api/metrics"),
}

# Streaming never ends under httpx; covered by test_realtime.py on live servers.
# Logout would kill the probe session; covered by test_auth.py.
SKIP = {
    ("GET", "/api/stream"),
    ("POST", "/api/auth/logout"),
}

# Every route that must answer 403 to a non-admin (require_role("admin")).
# If a new admin-only route appears, extend this set deliberately.
ADMIN_ONLY = frozenset(
    {
        ("GET", "/api/activity"),
        ("GET", "/api/activity/entities"),
        ("POST", "/api/automations"),
        ("PATCH", "/api/automations/{automation_id}"),
        ("DELETE", "/api/automations/{automation_id}"),
        ("POST", "/api/chats/quick-replies"),
        ("PATCH", "/api/chats/quick-replies/{reply_id}"),
        ("DELETE", "/api/chats/quick-replies/{reply_id}"),
        ("GET", "/api/chats/outbox"),
        ("POST", "/api/custom-fields"),
        ("PATCH", "/api/custom-fields/{field_id}"),
        ("DELETE", "/api/custom-fields/{field_id}"),
        ("POST", "/api/lost-reasons"),
        ("PATCH", "/api/lost-reasons/{reason_id}"),
        ("DELETE", "/api/lost-reasons/{reason_id}"),
        ("POST", "/api/pipelines"),
        ("PATCH", "/api/pipelines/{pipeline_id}"),
        ("DELETE", "/api/pipelines/{pipeline_id}"),
        ("POST", "/api/pipelines/{pipeline_id}/stages"),
        ("POST", "/api/pipelines/{pipeline_id}/stages/reorder"),
        ("PATCH", "/api/stages/{stage_id}"),
        ("DELETE", "/api/stages/{stage_id}"),
        ("GET", "/api/settings"),
        ("PATCH", "/api/settings"),
        ("GET", "/api/settings/bot-stages"),
        ("GET", "/api/settings/integrations"),
        ("DELETE", "/api/tags/{tag_id}"),
        ("GET", "/api/trash"),
        ("POST", "/api/users"),
        ("GET", "/api/users/{user_id}"),
        ("PATCH", "/api/users/{user_id}"),
    }
)


def _valid_admin_body(template: str) -> dict:
    """Bodies that pass request validation so the probe reaches the role check."""
    if template == "/api/automations":
        return {"name": "probe", "trigger_type": "deal_entered_stage"}
    if template == "/api/custom-fields":
        return {"entity": "deal", "key": "probe", "label": "Probe", "type": "text"}
    if template == "/api/lost-reasons":
        return {"name": "probe"}
    if template == "/api/pipelines":
        return {"name": "probe"}
    if template.endswith("/stages"):
        return {"name": "probe"}
    if template.endswith("/stages/reorder"):
        return {"ordered_ids": [DUMMY_UUID]}
    if template == "/api/chats/quick-replies":
        return {"title": "probe", "body": "probe"}
    if template == "/api/users":
        return {
            "email": "probe@example.com",
            "name": "probe",
            "password": "probe-password-1",
            "role": "manager",
        }
    if template in ("/api/settings",):
        return {}
    return {"name": "probe"}


def _concrete(template: str) -> str:
    """Fill path params with values that can never match real rows."""
    url = template.replace("{whatsapp_id}", "unknown-wa").replace("{full_path}", "nope")
    while "{" in url and "}" in url:
        start = url.index("{")
        end = url.index("}", start)
        url = url[:start] + DUMMY_UUID + url[end + 1 :]
    return url


def _iter_api_routes(app) -> list[tuple[str, str]]:
    found = []
    for path, methods in app.openapi()["paths"].items():
        if not path.startswith("/api/"):
            continue
        for method in methods:
            if method.lower() in ("options", "head", "trace"):
                continue
            found.append((method.upper(), path))
    return sorted(found)


async def test_every_route_requires_auth(client, app, settings):
    admin = await login_admin(client, settings)
    await make_manager(client, admin["csrf"])
    routes = _iter_api_routes(app)
    assert len(routes) > 60, f"openapi sweep found too few routes: {len(routes)}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
        for method, template in routes:
            if (method, template) in PUBLIC or (method, template) in SKIP:
                continue
            url = _concrete(template)
            if method == "GET":
                response = await anon.get(url)
            elif method == "DELETE":
                response = await anon.delete(url)
            else:
                response = await anon.request(method, url, json={})
            assert response.status_code == 401, f"{method} {template} -> {response.status_code}"


async def test_manager_matrix_admin_403_else_allowed(client, app, settings):
    admin = await login_admin(client, settings)
    manager = await make_manager(client, admin["csrf"])
    routes = _iter_api_routes(app)
    async with ManagerSession(app, manager["email"], manager["password"]) as mgr:
        assert mgr.client is not None
        headers = mgr.headers()
        for method, template in routes:
            if (method, template) in SKIP:
                continue
            url = _concrete(template)
            if method == "GET":
                # Analytics export needs its required query param.
                if template == "/api/analytics/export":
                    url += "?section=funnel"
                response = await mgr.client.get(url)
            elif method == "DELETE":
                response = await mgr.client.delete(url, headers=headers)
            elif (method, template) in ADMIN_ONLY:
                response = await mgr.client.request(
                    method, url, json=_valid_admin_body(template), headers=headers
                )
            else:
                body = {"body": "probe"} if "messages" in template else {}
                if template == "/api/contacts" and method == "POST":
                    body = {"custom": "not-a-dict"}
                response = await mgr.client.request(method, url, json=body, headers=headers)
            key = f"{method} {template}"
            if (method, template) in ADMIN_ONLY:
                assert response.status_code == 403, f"{key} -> {response.status_code}"
            else:
                assert response.status_code not in (
                    401,
                    403,
                ), f"{key} -> {response.status_code}: {response.text[:200]}"


async def test_allowlist_matches_openapi_admin_routes(app):
    """Guard against drift: every documented 403-capable admin route is listed."""
    # Re-derive admin-only routes from source markers and compare counts.
    import re
    from pathlib import Path

    routers = Path("backend/app/routers")
    found = 0
    for path in routers.glob("*.py"):
        src = path.read_text()
        # require_admin dependency or inline require_role("admin")
        found += len(re.findall(r"Depends\(require_admin\)", src))
        found += len(re.findall(r'Depends\(require_role\("admin"\)\)', src))
    # Each admin dependency guards exactly one endpoint function.
    assert found == len(ADMIN_ONLY), f"admin deps in code: {found}, allowlisted: {len(ADMIN_ONLY)}"
