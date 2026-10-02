from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("db_available")


async def test_root_serves_spa(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "KnewIT CRM" in response.text
    assert response.headers["cache-control"] == "no-cache"


async def test_spa_fallback_serves_index(client):
    for path in ("/deals", "/login", "/contacts?q=test"):
        response = await client.get(path)
        assert response.status_code == 200, path
        assert "KnewIT CRM" in response.text


async def test_api_unknown_is_json_404(client, settings):
    from backend.tests.conftest import login_admin

    await login_admin(client, settings)
    response = await client.get("/api/no-such-endpoint")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


async def test_frontend_prefers_dist_build():
    from backend.app.main import resolve_frontend_dir

    resolved = resolve_frontend_dir()
    assert resolved.name in ("dist", "frontend")


async def test_frontend_renders_no_raw_html():
    """Client content must never reach dangerouslySetInnerHTML (XSS surface)."""
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent.parent / "frontend" / "src"
    offenders = [
        str(path)
        for path in src.rglob("*.tsx")
        if "dangerouslySetInnerHTML" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
