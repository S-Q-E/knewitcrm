from __future__ import annotations

import asyncio
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.app.migrations import VERSION_TABLE

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


def test_dockerfile_pinned_bases_and_hardening():
    src = _read("Dockerfile")
    # Both stages pinned by digest (tag shown for readability).
    assert re.search(r"ARG PYTHON_IMAGE=python:3\.12[\.\d]*-slim@sha256:[0-9a-f]{64}", src)
    assert re.search(r"ARG NODE_IMAGE=node:20[\.\d]*-slim@sha256:[0-9a-f]{64}", src)
    assert "FROM ${PYTHON_IMAGE}" in src
    assert "FROM ${NODE_IMAGE} AS frontend-build" in src
    # Non-root runtime user.
    assert "USER appuser" in src
    assert "useradd" in src
    # Healthcheck against the Railway-provided port.
    assert "HEALTHCHECK" in src
    assert "/api/health" in src
    # Dependency layers are cached: manifests installed before sources.
    assert src.index("requirements.txt") < src.index("COPY backend")
    assert src.index("package-lock.json") < src.index("RUN npm run build")


def test_docker_entrypoint_migrates_then_serves():
    path = REPO_ROOT / "scripts" / "docker-entrypoint.sh"
    assert path.is_file()
    assert path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    assert subprocess.run(["sh", "-n", str(path)], check=False).returncode == 0
    src = path.read_text(encoding="utf-8")
    assert "alembic -c backend/alembic.ini upgrade head" in src
    assert "exec uvicorn backend.app.main:app" in src
    assert "--workers 1" in src  # P1-1: process-local event bus, see DECISIONS D26
    assert "--proxy-headers" in src
    assert '--forwarded-allow-ips="*"' in src
    # Migrations run from the entrypoint, not baked into the image build.
    assert "upgrade head" not in _read("Dockerfile")


def test_dockerignore_keeps_secrets_and_weight_out():
    lines = [
        line.strip()
        for line in _read(".dockerignore").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert ".git" in lines
    assert "node_modules" in lines
    assert "frontend/dist" in lines
    assert ".venv" in lines
    assert "tests" in lines
    assert any(line == ".env" or line.startswith(".env") for line in lines)
    for required in ("requirements.txt", "backend", "frontend", "scripts"):
        assert required not in lines, f"{required} must stay in the build context"


def test_railway_json_production_shape():
    cfg = json.loads(_read("railway.json"))
    assert cfg["build"]["builder"] == "DOCKERFILE"
    assert cfg["build"]["dockerfilePath"] == "Dockerfile"
    assert cfg["deploy"]["healthcheckPath"] == "/api/health"
    assert cfg["deploy"]["healthcheckTimeout"] >= 5
    assert cfg["deploy"]["restartPolicyType"] == "ON_FAILURE"


def test_smoke_script_shape_and_no_secrets():
    path = REPO_ROOT / "scripts" / "smoke.sh"
    assert path.is_file()
    assert path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    assert subprocess.run(["bash", "-n", str(path)], check=False).returncode == 0
    src = path.read_text(encoding="utf-8")
    for probe in ("/api/health", "/api/auth/login", "/api/deals", "/api/stream"):
        assert probe in src, f"smoke.sh must probe {probe}"
    assert "SEND_TEST_MESSAGE" in src and "TEST_WHATSAPP_ID" in src
    # Credentials only from the environment, empty allowed: the script
    # skips the authenticated checks itself (no secrets in CI `if:`).
    assert 'SMOKE_PASSWORD="${SMOKE_PASSWORD:-}"' in src
    assert "SMOKE_PASSWORD is empty" in src
    assert "admin-test-password" not in src
    # Quoted PASSWORD values must be env expansions or the "..." placeholder,
    # never hardcoded literals.
    for match in re.finditer(r"PASSWORD=\"([^\"]*)\"", src):
        assert "$" in match.group(1) or match.group(1) in (
            "",
            "...",
        ), f"literal password in smoke.sh: {match.group(0)}"
    assert not re.search(r"PASSWORD='.+?'", src)


def test_deploy_doc_covers_production_checklist():
    src = _read("docs/DEPLOY.md")
    for needle in (
        "staging",
        "production",
        "DATABASE_URL",
        "SECRET_KEY",
        "COOKIE_SECURE",
        "ALLOWED_ORIGINS",
        "ADMIN_EMAIL",
        "ADMIN_PASSWORD",
        "N8N_SEND_WEBHOOK_URL",
        "N8N_WEBHOOK_SECRET",
        "DEFAULT_TIMEZONE",
        "DEFAULT_CURRENCY",
        "crm_app",
        "GRANT SELECT ON knewit_",
        "UPDATE (current_stage, previous_stage, updated_at)",
        "permission denied",
        "Откат",
        "expand",
        "contract",
        "BACKUP.md",
        "smoke.sh",
        "RAILWAY_TOKEN",
        "healthcheck",
    ):
        assert needle in src, f"docs/DEPLOY.md must cover {needle!r}"


def test_migration_lock_key_is_unique_and_used():
    source = (REPO_ROOT / "backend" / "alembic" / "env.py").read_text(encoding="utf-8")
    # NOTE: env.py runs migrations on import (alembic loads it as config),
    # so the constant is asserted from source, never imported.
    match = re.search(r"MIGRATION_LOCK_KEY\s*=\s*(\d+)", source)
    assert match, "env.py must define MIGRATION_LOCK_KEY"
    assert int(match.group(1)) == 91030000
    for taken in ("91030001", "91030002", "91030003"):  # sync/notify/outbox workers
        assert taken not in match.group(0)
    assert "pg_advisory_lock" in source
    assert "pg_advisory_unlock" in source


@pytest.mark.usefixtures("db_available")
async def test_concurrent_migrations_both_succeed(settings):
    """Two simultaneous `upgrade head` runs (two booting containers)."""
    env = {
        **os.environ,
        "DATABASE_URL": settings.dsn,
        "ADMIN_EMAIL": "",
        "ADMIN_PASSWORD": "",
    }

    def run_upgrade() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )

    first, second = await asyncio.gather(
        asyncio.to_thread(run_upgrade), asyncio.to_thread(run_upgrade)
    )
    assert first.returncode == 0, first.stderr[-2000:]
    assert second.returncode == 0, second.stderr[-2000:]

    engine = create_async_engine(settings.sqlalchemy_url, connect_args=settings.connect_args)
    try:
        async with engine.connect() as conn:
            assert await conn.scalar(text(f"SELECT COUNT(*) FROM {VERSION_TABLE}")) >= 1
    finally:
        await engine.dispose()
