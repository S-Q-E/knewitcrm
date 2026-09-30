"""Seed local DB with knewit_* schema + test data (dev only)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SQL = ROOT / "tests" / "fixtures" / "knewit_schema.sql"
SEED_SQL = ROOT / "tests" / "fixtures" / "seed.sql"


def _dsn() -> str:
    url = os.getenv("DATABASE_URL", "postgresql://knewit:knewit@localhost:5432/knewit")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


async def main() -> None:
    conn = await asyncpg.connect(dsn=_dsn())
    try:
        for path in (SCHEMA_SQL, SEED_SQL):
            sql = path.read_text(encoding="utf-8")
            await conn.execute(sql)
            print(f"Applied {path.name}")
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
