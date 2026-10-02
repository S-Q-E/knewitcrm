from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import text

from backend.tests.conftest import unique_email

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

pytestmark = pytest.mark.usefixtures("db_available")


async def _purge_attempts(factory, *emails: str) -> None:
    async with factory() as session:
        await session.execute(
            text("DELETE FROM crm_login_attempts WHERE email = ANY(:emails)"),
            {"emails": list(emails)},
        )
        await session.commit()


async def test_docs_disabled_in_production(settings):
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    from backend.app.config import Settings
    from backend.app.main import create_app

    prod = Settings(
        cookie_secure=False,
        sync_enabled=False,
        outbox_enabled=False,
        notifications_enabled=False,
        realtime_enabled=False,
        app_env="production",
    )
    assert settings.app_env != "production"
    application = create_app(prod)
    async with LifespanManager(application):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as ac:
            for path in ("/docs", "/redoc", "/openapi.json", "/docs/"):
                response = await ac.get(path)
                assert response.status_code == 404, (path, response.status_code)
            body = (await ac.get("/docs")).json()
            assert body["error"]["code"] == "HTTP_ERROR"
            # The API itself stays up.
            assert (await ac.get("/api/health")).status_code == 200


async def test_docs_enabled_locally(client):
    assert (await client.get("/docs")).status_code == 200


async def test_login_timing_equalized(client, settings):
    """Unknown/inactive accounts must take as long as real ones (<=30% spread)."""
    from backend.tests.conftest import csrf_headers
    from backend.tests.crm_helpers import admin_csrf, engine_factory, make_manager

    engine, factory = engine_factory(settings)
    try:
        token = await admin_csrf(client, settings)
        manager = await make_manager(client, token)
        dormant = await make_manager(client, token)
        deactivated = await client.patch(
            f"/api/users/{dormant['user']['id']}",
            json={"is_active": False},
            headers=csrf_headers(token),
        )
        assert deactivated.status_code == 200, deactivated.text

        probes = {
            "existing": [(manager["email"], "wrong-password-1")] * 5,
            "unknown": [(unique_email("ghost"), "wrong-password-1") for _ in range(5)],
            "inactive": [(dormant["email"], dormant["password"])] * 5,
        }
        all_emails = [email for group in probes.values() for email, _ in group]

        async def attempt(email: str, password: str) -> float:
            started = time.perf_counter()
            response = await client.post(
                "/api/auth/login", json={"email": email, "password": password}
            )
            elapsed = time.perf_counter() - started
            assert response.status_code == 401, response.text
            return elapsed

        # Warm up caches/pools, then measure on a clean slate.
        for group in probes.values():
            await attempt(*group[0])
        await _purge_attempts(factory, *all_emails)

        means = {}
        for name, group in probes.items():
            samples = [await attempt(email, password) for email, password in group[1:]]
            means[name] = sum(samples) / len(samples)
        spread = (max(means.values()) - min(means.values())) / max(means.values())
        assert spread <= 0.30, means
    finally:
        await _purge_attempts(factory, manager["email"], dormant["email"])
        await engine.dispose()


async def test_email_flood_spares_owner_ip(client, settings, app):
    """20 failures from rotating IPs block strangers, not the owner's network."""
    from backend.tests.crm_helpers import ManagerSession, admin_csrf, engine_factory, make_manager

    engine, factory = engine_factory(settings)
    try:
        token = await admin_csrf(client, settings)
        manager = await make_manager(client, token)
        email = manager["email"]
        # Owner's successful login from the test peer (records the owner IP).
        async with ManagerSession(app, email, manager["password"]) as mgr:
            assert mgr.client is not None
            for i in range(20):
                flooded = await mgr.client.post(
                    "/api/auth/login",
                    json={"email": email, "password": "wrong-password-1"},
                    headers={"X-Forwarded-For": f"10.20.0.{i}"},
                )
                assert flooded.status_code == 401, i
            # Stranger IP with the right password: still blocked, with Retry-After.
            foreign = await mgr.client.post(
                "/api/auth/login",
                json={"email": email, "password": manager["password"]},
                headers={"X-Forwarded-For": "203.0.113.99"},
            )
            assert foreign.status_code == 429
            assert foreign.json()["error"]["code"] == "RATE_LIMITED"
            assert int(foreign.headers["retry-after"]) >= 1
            # Owner's own network with the right password: admitted.
            owner = await mgr.client.post(
                "/api/auth/login",
                json={"email": email, "password": manager["password"]},
            )
            assert owner.status_code == 200, owner.text
    finally:
        await _purge_attempts(factory, email)
        await engine.dispose()


async def test_login_limit_shared_between_workers(settings):
    """Two uvicorn workers (separate OS processes) share one DB budget."""
    import httpx
    from sqlalchemy.ext.asyncio import create_async_engine

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    env = {
        **os.environ,
        "DATABASE_URL": settings.dsn,
        "APP_ENV": "test",
        "SYNC_ENABLED": "false",
        "OUTBOX_ENABLED": "false",
        "NOTIFICATIONS_ENABLED": "false",
        "REALTIME_ENABLED": "false",
    }
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workers",
            "2",
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    email = unique_email("twoworkers")
    try:

        def scenario() -> None:
            base = f"http://127.0.0.1:{port}"
            with httpx.Client(timeout=30) as http:
                for _ in range(300):
                    try:
                        if http.get(f"{base}/api/health").status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    time.sleep(0.2)
                else:
                    raise AssertionError("uvicorn workers did not start")
                headers = {"X-Forwarded-For": "203.0.113.77"}
                payload = {"email": email, "password": "wrong-password-1"}
                # Requests spread over both workers; the 6th must still be 429.
                for _ in range(5):
                    response = http.post(f"{base}/api/auth/login", json=payload, headers=headers)
                    assert response.status_code == 401, response.text[:200]
                sixth = http.post(f"{base}/api/auth/login", json=payload, headers=headers)
                assert sixth.status_code == 429
                assert sixth.json()["error"]["code"] == "RATE_LIMITED"

        await asyncio.to_thread(scenario)
    finally:
        proc.terminate()
        await asyncio.to_thread(proc.wait, 30)
        engine = create_async_engine(settings.sqlalchemy_url, connect_args=settings.connect_args)
        async with engine.connect() as conn:
            await conn.execute(
                text("DELETE FROM crm_login_attempts WHERE email = :email"),
                {"email": email},
            )
            await conn.commit()
        await engine.dispose()


async def test_422_details_have_no_input(client):
    response = await client.post("/api/auth/login", json={})
    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert isinstance(details, list) and details
    for item in details:
        assert set(item) == {"loc", "msg", "type"}, item


def test_sentry_scrub_removes_bodies_and_sql_params():
    from backend.app.services.sentry import scrub_sentry_event

    event = {
        "request": {
            "url": "https://crm.example.com/api/auth/login",
            "method": "POST",
            "data": {"email": "a@example.com", "password": "secret-1"},
        },
        "breadcrumbs": {
            "values": [
                {
                    "type": "query",
                    "data": {
                        "sql": "SELECT * FROM crm_users WHERE email = %(email)s",
                        "params": {"email": "a@example.com"},
                    },
                },
                {"type": "http", "data": {"url": "https://x", "status_code": 200}},
            ]
        },
    }
    out = scrub_sentry_event(event, None)
    assert "data" not in out["request"]
    assert out["request"]["method"] == "POST"
    assert out["breadcrumbs"]["values"][0]["data"] == {
        "sql": "SELECT * FROM crm_users WHERE email = %(email)s"
    }
    assert out["breadcrumbs"]["values"][1]["data"]["status_code"] == 200
    assert scrub_sentry_event({}, None) == {}


def test_sentry_init_wires_before_send(monkeypatch):
    import sentry_sdk

    from backend.app.services.sentry import init_sentry, scrub_sentry_event

    captured: dict = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: captured.update(kwargs) or True)

    class DSNSettings:
        sentry_dsn = "https://x@y/1"
        sentry_environment = ""
        app_env = "test"

    assert init_sentry(DSNSettings()) is True
    assert captured.get("before_send") is scrub_sentry_event


def test_ci_smoke_has_no_secret_conditions_and_actionlint():
    import re

    src = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    smoke_block = src.split("Staging smoke", 1)[1].split("deploy-production", 1)[0]
    assert not re.search(r"(?m)^\s*if:", smoke_block)
    assert "SMOKE_PASSWORD" in smoke_block  # passed via env, skipped in-script
    assert "actionlint:" in src
    assert "./actionlint" in src
