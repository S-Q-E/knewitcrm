from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

os.environ.setdefault("DATABASE_URL", "postgresql://knewit:knewit@localhost:5432/knewit")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ADMIN_EMAIL", "admin-test@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "admin-test-password-1")

from backend.app.config import Settings  # noqa: E402
from backend.app.deps import get_settings  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.security import CSRF_HEADER  # noqa: E402
from backend.app.services.ratelimit import login_limiter  # noqa: E402


@pytest.fixture(scope="session")
def settings() -> Settings:
    # Test traffic is plain http://test, so Secure cookies would never be sent
    # back. Production keeps COOKIE_SECURE=true (see .env.example).
    # The sync worker is disabled: sync tests drive run_sync_cycle directly.
    # All background loops stay off so tests observe only what they trigger.
    return Settings(
        cookie_secure=False,
        sync_enabled=False,
        outbox_enabled=False,
        notifications_enabled=False,
        realtime_enabled=False,
    )


@pytest.fixture(scope="session")
async def db_available(settings):
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(settings.sqlalchemy_url, connect_args=settings.connect_args)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("Postgres is not available")
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
async def migrated(db_available):
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "backend" / "alembic"))
    # env.py calls asyncio.run(), which needs a thread without a running loop.
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest.fixture(autouse=True)
def clean_rate_limiter():
    login_limiter.clear()
    yield
    login_limiter.clear()


@pytest.fixture()
def app(settings):
    application = create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    return application


@pytest.fixture()
async def client(app, migrated):
    from asgi_lifespan import LifespanManager

    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


def csrf_headers(token: str) -> dict:
    return {CSRF_HEADER: token}


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


async def login(ac: AsyncClient, email: str, password: str) -> dict:
    """Log in, assert success, return the CSRF token (session lives in the jar)."""
    response = await ac.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    token = ac.cookies.get("crm_csrf")
    assert token, "CSRF cookie was not set"
    assert response.json()["email"] == email.lower()
    return {"csrf": token, "user": response.json()}


async def login_admin(ac: AsyncClient, settings: Settings) -> dict:
    assert settings.admin_email and settings.admin_password
    return await login(ac, settings.admin_email, settings.admin_password)


@pytest.fixture()
async def tx_session(settings, db_available):
    """Transactional session with rollback (for isolated write tests)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(settings.sqlalchemy_url, connect_args=settings.connect_args)
    connection = await engine.connect()
    transaction = await connection.begin()
    try:
        factory = async_sessionmaker(bind=connection, expire_on_commit=False)
        async with factory() as session:
            yield session
    finally:
        await transaction.rollback()
        await connection.close()
        await engine.dispose()
