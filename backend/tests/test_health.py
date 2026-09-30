from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("db_available")


async def test_health_is_public(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert response.headers["x-request-id"]


async def test_ready_is_public(client):
    response = await client.get("/api/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["db"] == "up"


async def test_protected_route_requires_auth(client):
    response = await client.get("/api/stats")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_wrong_credentials_rejected(client):
    response = await client.get("/api/stats", headers={"Authorization": "Basic d3Jvbmc6d3Jvbmc="})
    assert response.status_code == 401


async def test_validation_error_format(client, auth_headers):
    response = await client.get("/api/leads?limit=9999", headers=auth_headers)
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert response.headers["x-request-id"]
