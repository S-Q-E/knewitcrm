from __future__ import annotations

import os
from typing import Optional

import asyncpg

_pool: Optional[asyncpg.Pool] = None


def _build_dsn() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        # asyncpg не принимает схему postgres://
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        return url

    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    user = os.getenv("PGUSER", "postgres")
    password = os.getenv("PGPASSWORD", "")
    database = os.getenv("PGDATABASE", "railway")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def _ssl_setting():
    val = os.getenv("PGSSL", "").lower()
    if val in ("1", "true", "yes"):
        return True
    if val in ("0", "false", "no"):
        return False
    # авто-детект: публичный прокси Railway требует SSL, внутренний — нет
    dsn = _build_dsn()
    if "proxy.rlwy.net" in dsn or "railway.app" in dsn:
        return True
    return False


async def init_pool() -> None:
    global _pool
    if _pool is not None:
        return
    _pool = await asyncpg.create_pool(
        dsn=_build_dsn(),
        min_size=1,
        max_size=8,
        ssl=_ssl_setting(),
        command_timeout=30,
    )


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool is not initialized")
    return _pool