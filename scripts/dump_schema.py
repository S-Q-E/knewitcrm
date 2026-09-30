"""Dump knewit_* schema (read-only) into docs/db_schema.md.

Usage:
    DATABASE_URL=postgresql://... python scripts/dump_schema.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import asyncpg

OUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "db_schema.md"


async def _fetch_tables(conn) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public' AND tablename LIKE 'knewit\\_%'
        ORDER BY tablename
        """
    )
    return [r["tablename"] for r in rows]


async def _fetch_columns(conn, table: str):
    return await conn.fetch(
        """
        SELECT column_name, data_type, udt_name, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = $1
        ORDER BY ordinal_position
        """,
        table,
    )


async def _fetch_pk(conn, table: str):
    return await conn.fetch(
        """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.table_schema = 'public' AND tc.table_name = $1
          AND tc.constraint_type = 'PRIMARY KEY'
        ORDER BY kcu.ordinal_position
        """,
        table,
    )


async def _fetch_fks(conn, table: str):
    return await conn.fetch(
        """
        SELECT
          kcu.column_name,
          ccu.table_name AS foreign_table,
          ccu.column_name AS foreign_column,
          tc.constraint_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
        WHERE tc.table_schema = 'public' AND tc.table_name = $1
          AND tc.constraint_type = 'FOREIGN KEY'
        """,
        table,
    )


async def _fetch_indexes(conn, table: str):
    return await conn.fetch(
        """
        SELECT indexname, indexdef FROM pg_indexes
        WHERE schemaname = 'public' AND tablename = $1
        ORDER BY indexname
        """,
        table,
    )


async def _fetch_distinct(conn, sql: str):
    try:
        return await conn.fetch(sql)
    except Exception as exc:  # keep dump working even if a column is missing
        return [{"_error": str(exc)}]


def _dsn() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


async def main() -> None:
    conn = await asyncpg.connect(dsn=_dsn())
    try:
        tables = await _fetch_tables(conn)
        lines: list[str] = ["# DB schema (knewit_*)", ""]
        lines.append(f"Tables found: {', '.join(tables) if tables else '(none)'}")
        lines.append("")
        for table in tables:
            lines.append(f"## {table}")
            lines.append("")
            cols = await _fetch_columns(conn, table)
            lines.append("| column | type | nullable | default |")
            lines.append("|---|---|---|---|")
            for c in cols:
                if c["data_type"] == "USER-DEFINED":
                    dtype = c["udt_name"]
                else:
                    dtype = c["data_type"]
                default = c["column_default"] or ""
                col = c["column_name"]
                lines.append(f"| {col} | {dtype} | {c['is_nullable']} | {default} |")
            lines.append("")
            pk = await _fetch_pk(conn, table)
            lines.append(f"PK: {', '.join(r['column_name'] for r in pk) or '(none)'}")
            lines.append("")
            fks = await _fetch_fks(conn, table)
            if fks:
                lines.append("FKs:")
                for fk in fks:
                    target = f"{fk['foreign_table']}.{fk['foreign_column']}"
                    lines.append(f"- {fk['column_name']} -> {target} ({fk['constraint_name']})")
            else:
                lines.append("FKs: (none)")
            lines.append("")
            idx = await _fetch_indexes(conn, table)
            lines.append("Indexes:")
            for i in idx:
                lines.append(f"- {i['indexname']}: {i['indexdef']}")
            if not idx:
                lines.append("- (none)")
            lines.append("")

        lines.append("## Distinct values")
        lines.append("")
        stages = await _fetch_distinct(
            conn,
            "SELECT current_stage, status, COUNT(*) AS cnt "
            "FROM knewit_leads GROUP BY current_stage, status "
            "ORDER BY cnt DESC",
        )
        lines.append("### knewit_leads.current_stage + status (with counts)")
        lines.append("")
        for r in stages:
            lines.append(f"- {dict(r)}")
        lines.append("")
        statuses = await _fetch_distinct(
            conn,
            "SELECT status, COUNT(*) AS cnt " "FROM knewit_leads GROUP BY status ORDER BY cnt DESC",
        )
        lines.append("### knewit_leads.status (with counts)")
        lines.append("")
        for r in statuses:
            lines.append(f"- {dict(r)}")
        lines.append("")
        events = await _fetch_distinct(
            conn,
            "SELECT event_type, COUNT(*) AS cnt "
            "FROM knewit_events GROUP BY event_type ORDER BY cnt DESC",
        )
        lines.append("### knewit_events.event_type (with counts)")
        lines.append("")
        for r in events:
            lines.append(f"- {dict(r)}")
        lines.append("")

        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
        print(f"Wrote {OUT_PATH}")
    finally:
        await conn.close()


if __name__ == "__main__":
    import asyncio

    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
