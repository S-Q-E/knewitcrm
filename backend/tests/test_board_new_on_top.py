from __future__ import annotations

import importlib.util
import json
import urllib.parse
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from backend.app.workers.sync_worker import run_sync_cycle
from backend.tests.crm_helpers import (
    admin_csrf,
    create_contact,
    create_deal,
    default_pipeline,
    engine_factory,
    open_stage,
    purge_contacts,
    purge_pipelines,
)

pytestmark = pytest.mark.usefixtures("db_available")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATION_SQL = (
    "WITH first_open AS ("
    " SELECT DISTINCT ON (pipeline_id) id AS stage_id, pipeline_id"
    " FROM crm_stages WHERE kind = 'open' ORDER BY pipeline_id, sort, name"
    "), ranked AS ("
    " SELECT d.id,"
    " ROW_NUMBER() OVER ("
    " PARTITION BY d.stage_id ORDER BY d.created_at DESC, d.id"
    " ) AS rn"
    " FROM crm_deals d JOIN first_open f ON f.stage_id = d.stage_id"
    " WHERE d.deleted_at IS NULL"
    ")"
    " UPDATE crm_deals d SET position = r.rn FROM ranked r WHERE d.id = r.id"
)


def _wa(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}@c.us"


async def _first_open_stage_id(factory):
    """Stage id sync_worker treats as «Новые лиды» for the default pipeline."""
    async with factory() as session:
        return (
            await session.execute(
                text(
                    "SELECT s.id FROM crm_stages s"
                    " JOIN crm_pipelines p ON p.id = s.pipeline_id"
                    " WHERE p.is_default AND s.kind = 'open'"
                    " ORDER BY s.sort, s.name LIMIT 1"
                )
            )
        ).scalar_one()


async def _stage_min(factory, stage_id) -> Decimal | None:
    async with factory() as session:
        return (
            await session.execute(
                text(
                    "SELECT MIN(position) FROM crm_deals"
                    " WHERE stage_id = :s AND deleted_at IS NULL"
                ),
                {"s": str(stage_id)},
            )
        ).scalar()


async def _purge_was(factory, was: list[str]) -> None:
    async with factory() as session:
        contact_ids = (
            (
                await session.execute(
                    text("SELECT id FROM crm_contacts WHERE whatsapp_id = ANY(:ids)"),
                    {"ids": was},
                )
            )
            .scalars()
            .all()
        )
    await purge_contacts(factory, [str(i) for i in contact_ids])
    async with factory() as session:
        await session.execute(
            text("DELETE FROM crm_conversation_state WHERE whatsapp_id = ANY(:ids)"),
            {"ids": was},
        )
        await session.execute(
            text("DELETE FROM knewit_leads WHERE whatsapp_id = ANY(:ids)"), {"ids": was}
        )
        await session.commit()


async def test_sync_new_deal_lands_on_top(settings):
    engine, factory = engine_factory(settings)
    wa = _wa("7999777")
    try:
        stage_id = await _first_open_stage_id(factory)
        before = await _stage_min(factory, stage_id)
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO knewit_leads (whatsapp_id, name, current_stage, status)"
                    " VALUES (:wa, 'Top Test', 'НОВЫЙ_ЛИД', 'ACTIVE')"
                ),
                {"wa": wa},
            )
            await session.commit()
        stats = await run_sync_cycle(factory)
        assert stats is not None
        assert stats.deals_created >= 1
        async with factory() as session:
            pos = (
                await session.execute(
                    text(
                        "SELECT d.position FROM crm_deals d"
                        " JOIN crm_contacts c ON c.id = d.contact_id"
                        " WHERE c.whatsapp_id = :wa AND d.deleted_at IS NULL"
                    ),
                    {"wa": wa},
                )
            ).scalar_one()
        if before is None:
            assert Decimal(pos) == Decimal(0)
        else:
            assert Decimal(pos) == Decimal(before) - 1
    finally:
        await _purge_was(factory, [wa])
        await engine.dispose()


async def test_sync_batch_keeps_creation_order(settings):
    engine, factory = engine_factory(settings)
    tag = uuid.uuid4().hex[:6]
    was = [f"799988{i}{tag}@c.us" for i in range(3)]
    try:
        stage_id = await _first_open_stage_id(factory)
        before = await _stage_min(factory, stage_id)
        async with factory() as session:
            for n, wa in enumerate(was):
                await session.execute(
                    text(
                        "INSERT INTO knewit_leads (whatsapp_id, name, current_stage, status)"
                        " VALUES (:wa, :name, 'НОВЫЙ_ЛИД', 'ACTIVE')"
                    ),
                    {"wa": wa, "name": f"Batch {n}"},
                )
            await session.commit()
        stats = await run_sync_cycle(factory)
        assert stats is not None
        assert stats.deals_created >= 3
        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT c.whatsapp_id AS wa, d.position AS pos FROM crm_deals d"
                            " JOIN crm_contacts c ON c.id = d.contact_id"
                            " WHERE c.whatsapp_id = ANY(:ids) AND d.deleted_at IS NULL"
                            " ORDER BY d.position ASC, d.id ASC"
                        ),
                        {"ids": was},
                    )
                )
                .mappings()
                .all()
            )
        assert [r["wa"] for r in rows] == was
        positions = [Decimal(r["pos"]) for r in rows]
        assert positions == sorted(positions)
        assert all(b - a == 1 for a, b in zip(positions, positions[1:], strict=False))
        if before is None:
            assert positions == [Decimal(-2), Decimal(-1), Decimal(0)]
        else:
            assert positions[-1] == Decimal(before) - 1
            assert all(p < Decimal(before) for p in positions)
    finally:
        await _purge_was(factory, was)
        await engine.dispose()


async def test_create_deal_lands_on_top(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipeline = await default_pipeline(client)
        stage = open_stage(pipeline)
        before = await _stage_min(factory, stage["id"])
        contact = await create_contact(client, token, whatsapp_id=_wa("7999666"))
        contact_ids.append(contact["id"])
        deal = await create_deal(client, token, contact["id"], pipeline)
        if before is None:
            assert Decimal(str(deal["position"])) == Decimal(0)
        else:
            assert Decimal(str(deal["position"])) == Decimal(before) - 1
        board = await client.get(f"/api/deals/board?pipeline_id={pipeline['id']}&limit=200")
        assert board.status_code == 200
        column = next(c for c in board.json()["columns"] if c["stage_id"] == stage["id"])
        assert column["items"][0]["id"] == deal["id"]
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_board_pagination_with_negative_positions(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipeline = await default_pipeline(client)
        stage = open_stage(pipeline)
        for _ in range(3):
            contact = await create_contact(client, token, whatsapp_id=_wa("7999555"))
            contact_ids.append(contact["id"])
            await create_deal(client, token, contact["id"], pipeline)

        async def column_page(limit: int, cursor: str | None):
            params = {"pipeline_id": pipeline["id"], "limit": str(limit), "cursors": "{}"}
            if cursor is not None:
                params["cursors"] = json.dumps({stage["id"]: cursor})
            query = urllib.parse.urlencode(params)
            response = await client.get(f"/api/deals/board?{query}")
            assert response.status_code == 200
            return next(c for c in response.json()["columns"] if c["stage_id"] == stage["id"])

        full = await column_page(200, None)
        full_ids = [i["id"] for i in full["items"]]
        assert len(full_ids) >= 3
        positions = [Decimal(str(i["position"])) for i in full["items"]]
        assert positions == sorted(positions)

        walked: list[str] = []
        cursor: str | None = None
        for _ in range(50):
            page = await column_page(2, cursor)
            walked.extend(i["id"] for i in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert walked == full_ids
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_backfill_first_open_only(settings):
    engine, factory = engine_factory(settings)
    suffix = uuid.uuid4().hex[:6]
    pipeline_id = str(uuid.uuid4())
    first_id = str(uuid.uuid4())
    work_id = str(uuid.uuid4())
    contact_ids = [str(uuid.uuid4()) for _ in range(4)]
    deal_ids = [str(uuid.uuid4()) for _ in range(4)]
    try:
        async with factory() as session:
            await session.execute(
                text("INSERT INTO crm_pipelines (id, name) VALUES (:id, :name)"),
                {"id": pipeline_id, "name": f"Backfill Pipe {suffix}"},
            )
            await session.execute(
                text(
                    "INSERT INTO crm_stages (id, pipeline_id, name, sort, kind)"
                    " VALUES (:id, :p, 'First', 0, 'open'), (:work, :p, 'Working', 5, 'open')"
                ),
                {"id": first_id, "work": work_id, "p": pipeline_id},
            )
            for n, cid in enumerate(contact_ids):
                await session.execute(
                    text(
                        "INSERT INTO crm_contacts (id, whatsapp_id, name)"
                        " VALUES (:id, :wa, :name)"
                    ),
                    {"id": cid, "wa": f"799944{n}{suffix}@c.us", "name": f"BF {n}"},
                )
            deals = [
                # (deal, contact, stage, title, position, created_at): scrambled positions.
                (
                    deal_ids[0],
                    contact_ids[0],
                    first_id,
                    "Old",
                    30,
                    datetime(2024, 1, 1, tzinfo=UTC),
                ),
                (
                    deal_ids[1],
                    contact_ids[1],
                    first_id,
                    "Mid",
                    10,
                    datetime(2024, 6, 1, tzinfo=UTC),
                ),
                (
                    deal_ids[2],
                    contact_ids[2],
                    first_id,
                    "Fresh",
                    20,
                    datetime(2025, 1, 1, tzinfo=UTC),
                ),
                (
                    deal_ids[3],
                    contact_ids[3],
                    work_id,
                    "Work",
                    7,
                    datetime(2024, 3, 1, tzinfo=UTC),
                ),
            ]
            for did, cid, sid, title, pos, created in deals:
                await session.execute(
                    text(
                        "INSERT INTO crm_deals"
                        " (id, contact_id, pipeline_id, stage_id, title, status,"
                        " position, created_at)"
                        " VALUES (:id, :c, :p, :s, :t, 'open', :pos, :created)"
                    ),
                    {
                        "id": did,
                        "c": cid,
                        "p": pipeline_id,
                        "s": sid,
                        "t": f"{title} {suffix}",
                        "pos": pos,
                        "created": created,
                    },
                )
            await session.commit()

        async with factory() as session:
            await session.execute(text(MIGRATION_SQL))
            await session.commit()

        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT title, position FROM crm_deals"
                            " WHERE pipeline_id = :p AND deleted_at IS NULL"
                            " ORDER BY position ASC"
                        ),
                        {"p": pipeline_id},
                    )
                )
                .mappings()
                .all()
            )
        ordered = [(r["title"].split()[0], Decimal(r["position"])) for r in rows]
        assert [t for t, _ in ordered] == ["Fresh", "Mid", "Old", "Work"]
        assert [p for _, p in ordered[:3]] == [Decimal(1), Decimal(2), Decimal(3)]
        assert ordered[3][1] == Decimal(7)
    finally:
        await purge_contacts(factory, contact_ids)
        await purge_pipelines(factory, [pipeline_id])
        await engine.dispose()


def test_migration_downgrade_is_noop():
    path = REPO_ROOT / "backend" / "alembic" / "versions" / "0020_board_new_on_top.py"
    spec = importlib.util.spec_from_file_location("migration_0020", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0020_board_new_on_top"
    assert module.down_revision == "0019_login_attempts"
    # Downgrade must not touch data: old positions are gone, re-sorting would
    # only destroy the backfilled order and later manual moves.
    assert module.downgrade() is None
