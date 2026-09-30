from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

os.environ.setdefault("DATABASE_URL", "postgresql://knewit:knewit@localhost:5432/knewit")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("CRM_BASIC_USER", "test")
os.environ.setdefault("CRM_BASIC_PASS", "test")

from backend.app.config import Settings  # noqa: E402
from backend.app.deps import get_settings  # noqa: E402
from backend.app.main import create_app  # noqa: E402


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


@pytest.fixture()
def app(settings):
    application = create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    return application


@pytest.fixture()
async def client(app):
    from asgi_lifespan import LifespanManager

    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


@pytest.fixture()
def auth_headers(settings):
    token = base64.b64encode(f"{settings.basic_user}:{settings.basic_pass}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


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


@pytest.fixture()
async def tx_session(settings, db_available):
    """Transactional session with rollback (for future write tests)."""
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
