"""SSE load test: 50 concurrent connections, leak check. Not part of pytest.

Starts its own uvicorn on port 8023 against the local Postgres, opens 50
SSE streams, triggers one bot_paused event via the API, and asserts every
connection receives it. Then closes everything and asserts the server is
still responsive (no leaked connections breaking the app).

Usage: python scripts/stream_load_test.py
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

BASE = "http://127.0.0.1:8023"
CONNECTIONS = 50
WA = "77010000001@c.us"

ENV = {
    **os.environ,
    "DATABASE_URL": "postgresql://knewit:knewit@localhost:5432/knewit",
    "SECRET_KEY": "load-test-secret",
    "ADMIN_EMAIL": "admin-test@example.com",
    "ADMIN_PASSWORD": "admin-test-password-1",
    "COOKIE_SECURE": "false",
    "SYNC_ENABLED": "false",
}


async def read_event(lines):
    name = ""
    async for line in lines:
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            return {"name": name, "data": json.loads(line[len("data:") :].strip())}
    raise AssertionError("stream ended without an event")


async def main() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", "8023"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=ENV,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        timeout = httpx.Timeout(connect=10, read=None, write=10, pool=100)
        async with httpx.AsyncClient(timeout=timeout) as probe:
            for _ in range(120):
                try:
                    ready = await probe.get(f"{BASE}/api/ready")
                    if ready.json().get("ready"):
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.5)
            else:
                raise RuntimeError("server did not start")
            login = await probe.post(
                f"{BASE}/api/auth/login",
                json={"email": "admin-test@example.com", "password": "admin-test-password-1"},
            )
            assert login.status_code == 200, login.text

        started = time.perf_counter()
        results: list = [None] * CONNECTIONS
        async with httpx.AsyncClient(base_url=BASE, timeout=timeout) as client:
            await client.post(
                "/api/auth/login",
                json={
                    "email": "admin-test@example.com",
                    "password": "admin-test-password-1",
                },
            )
            csrf = client.cookies.get("crm_csrf")
            assert csrf
            streams = [client.stream("GET", "/api/stream") for _ in range(CONNECTIONS)]
            responses = [await context.__aenter__() for context in streams]
            try:
                for response in responses:
                    assert response.status_code == 200, response.status_code
                results = [response.aiter_lines() for response in responses]
                for lines in results:
                    first = await asyncio.wait_for(lines.__anext__(), timeout=20)
                    assert first.startswith(":")
                print(f"opened {CONNECTIONS} streams in {time.perf_counter() - started:.1f}s")

                paused = await client.post(
                    f"/api/chats/{WA}/bot/pause", headers={"X-CSRF-Token": csrf}
                )
                assert paused.status_code == 200, paused.text
                deadline = time.perf_counter() + 30
                received = 0
                for lines in results:
                    remaining = max(1, deadline - time.perf_counter())
                    event = await asyncio.wait_for(read_event(lines), timeout=remaining)
                    assert event["name"] == "bot_paused", event
                    received += 1
                print(f"all {received} connections received bot_paused")

                resumed = await client.post(
                    f"/api/chats/{WA}/bot/resume", headers={"X-CSRF-Token": csrf}
                )
                assert resumed.status_code == 200
            finally:
                for context in streams:
                    await context.__aexit__(None, None, None)
        # Clients closed: server must stay responsive (no leaked state breaking it).
        async with httpx.AsyncClient(timeout=httpx.Timeout(10)) as probe:
            for _ in range(3):
                health = await probe.get(f"{BASE}/api/ready")
                assert health.json().get("ready")
        print("server responsive after close; no connection errors")
        print("LOAD TEST PASSED")
    finally:
        proc.terminate()
        proc.wait(timeout=15)


if __name__ == "__main__":
    asyncio.run(main())
