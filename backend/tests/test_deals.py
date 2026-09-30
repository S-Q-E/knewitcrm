from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from backend.tests.conftest import csrf_headers
from backend.tests.crm_helpers import (
    admin_csrf,
    assert_logged,
    create_contact,
    create_deal,
    default_pipeline,
    engine_factory,
    open_stage,
    purge_contacts,
    purge_rows,
)

pytestmark = pytest.mark.usefixtures("db_available")


def _wa() -> str:
    return f"7999{uuid.uuid4().hex[:8]}@c.us"


async def _lead_row(factory, wa: str, stage: str, status: str = "ACTIVE") -> None:
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO knewit_leads (whatsapp_id, name, current_stage, status)"
                " VALUES (:wa, 'Board Bot', :stage, :status)"
            ),
            {"wa": wa, "stage": stage, "status": status},
        )
        await session.commit()


async def test_deal_crud_and_status_flow(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    reason_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipeline = await default_pipeline(client)
        stage = open_stage(pipeline)
        contact = await create_contact(client, token, whatsapp_id=_wa())
        contact_ids.append(contact["id"])
        deal = await create_deal(client, token, contact["id"], pipeline)
        deal_id = deal["id"]
        await assert_logged(factory, "deal", deal_id, "deal_created")

        bad_stage = await client.post(
            "/api/deals",
            json={
                "contact_id": contact["id"],
                "pipeline_id": pipeline["id"],
                "stage_id": "00000000-0000-0000-0000-000000000000",
                "title": "X",
            },
            headers=csrf_headers(token),
        )
        assert bad_stage.status_code == 422

        won_stage = next(s for s in pipeline["stages"] if s["kind"] == "won")
        closed_stage = await client.post(
            "/api/deals",
            json={
                "contact_id": contact["id"],
                "pipeline_id": pipeline["id"],
                "stage_id": won_stage["id"],
                "title": "X",
            },
            headers=csrf_headers(token),
        )
        assert closed_stage.status_code == 422

        won = await client.patch(
            f"/api/deals/{deal_id}",
            json={"status": "won"},
            headers=csrf_headers(token),
        )
        assert won.status_code == 200
        assert won.json()["status"] == "won"
        assert won.json()["closed_at"] is not None

        reopened = await client.patch(
            f"/api/deals/{deal_id}",
            json={"status": "open"},
            headers=csrf_headers(token),
        )
        assert reopened.json()["closed_at"] is None

        lost_bare = await client.patch(
            f"/api/deals/{deal_id}",
            json={"status": "lost"},
            headers=csrf_headers(token),
        )
        assert lost_bare.status_code == 422

        reason = (
            await client.post(
                "/api/lost-reasons",
                json={"name": f"r-{uuid.uuid4().hex[:8]}"},
                headers=csrf_headers(token),
            )
        ).json()
        reason_ids.append(reason["id"])
        lost = await client.patch(
            f"/api/deals/{deal_id}",
            json={"status": "lost", "lost_reason_id": reason["id"]},
            headers=csrf_headers(token),
        )
        assert lost.status_code == 200
        assert lost.json()["lost_reason_id"] == reason["id"]
        assert lost.json()["closed_at"] is not None
        assert stage["id"]  # open stage fixture used above
    finally:
        await purge_contacts(factory, contact_ids)
        await purge_rows(factory, "crm_lost_reasons", reason_ids)
        await engine.dispose()


async def test_board_grouping_and_cursor(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipeline = await default_pipeline(client)
        stage = open_stage(pipeline)
        for _ in range(3):
            contact = await create_contact(client, token, whatsapp_id=_wa())
            contact_ids.append(contact["id"])
            await create_deal(
                client,
                token,
                contact["id"],
                pipeline,
                title=f"BoardDeal {uuid.uuid4().hex[:6]}",
                amount=1000,
            )

        board = await client.get(f"/api/deals/board?pipeline_id={pipeline['id']}&limit=2")
        assert board.status_code == 200
        column = next(c for c in board.json()["columns"] if c["stage_id"] == stage["id"])
        assert column["total"] >= 3
        assert column["amount_total"] >= 3000
        assert len(column["items"]) == 2
        assert column["next_cursor"]

        import json as jsonlib
        import urllib.parse

        cursors = urllib.parse.quote(jsonlib.dumps({stage["id"]: column["next_cursor"]}))
        page2 = await client.get(
            f"/api/deals/board?pipeline_id={pipeline['id']}&limit=2&cursors={cursors}"
        )
        column2 = next(c for c in page2.json()["columns"] if c["stage_id"] == stage["id"])
        first_ids = {i["id"] for i in column["items"]}
        second_ids = {i["id"] for i in column2["items"]}
        assert first_ids.isdisjoint(second_ids)
        assert second_ids, "second page must contain the remaining deal"
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_move_locks_and_calls_bridge(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipeline = await default_pipeline(client)
        stages = [s for s in pipeline["stages"] if s["kind"] == "open"]
        src, dst = stages[0]["id"], stages[1]["id"]
        wa = _wa()
        contact = await create_contact(client, token, whatsapp_id=wa)
        contact_ids.append(contact["id"])
        await _lead_row(factory, wa, stages[0]["bot_stage_key"] or "НОВЫЙ_ЛИД")
        deal = await create_deal(client, token, contact["id"], pipeline, stage_id=src)

        # Same-stage reorder: no lock, no history.
        reorder = await client.post(
            f"/api/deals/{deal['id']}/move",
            json={"stage_id": src, "position": 0.5},
            headers=csrf_headers(token),
        )
        assert reorder.status_code == 200
        assert reorder.json()["stage_locked"] is False
        assert float(reorder.json()["position"]) == 0.5

        moved = await client.post(
            f"/api/deals/{deal['id']}/move",
            json={"stage_id": dst, "position": 1.25},
            headers=csrf_headers(token),
        )
        assert moved.status_code == 200
        body = moved.json()
        assert body["stage_id"] == dst
        assert body["stage_locked"] is True
        assert float(body["position"]) == 1.25
        await assert_logged(factory, "deal", deal["id"], "deal_moved")

        async with factory() as session:
            history = (
                (
                    await session.execute(
                        text(
                            "SELECT source, changed_by IS NOT NULL AS by_user"
                            " FROM crm_deal_stage_history WHERE deal_id = :id ORDER BY at"
                        ),
                        {"id": deal["id"]},
                    )
                )
                .mappings()
                .all()
            )
            assert [h["source"] for h in history] == ["manager", "manager"]
            assert history[-1]["by_user"] is True
            lead = (
                await session.execute(
                    text("SELECT current_stage FROM knewit_leads WHERE whatsapp_id = :wa"),
                    {"wa": wa},
                )
            ).scalar_one()
            assert lead == stages[1]["bot_stage_key"]
            event = (
                (
                    await session.execute(
                        text(
                            "SELECT event_type, to_stage FROM knewit_events"
                            " WHERE whatsapp_id = :wa ORDER BY id DESC LIMIT 1"
                        ),
                        {"wa": wa},
                    )
                )
                .mappings()
                .one()
            )
            assert event["event_type"] == "manual_stage_change"

        unlocked = await client.post(
            f"/api/deals/{deal['id']}/unlock-bot", headers=csrf_headers(token)
        )
        assert unlocked.json()["stage_locked"] is False
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_move_to_lost_requires_reason(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    reason_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipeline = await default_pipeline(client)
        lost_stage = next(s for s in pipeline["stages"] if s["kind"] == "lost")
        contact = await create_contact(client, token, whatsapp_id=_wa())
        contact_ids.append(contact["id"])
        deal = await create_deal(client, token, contact["id"], pipeline)

        bare = await client.post(
            f"/api/deals/{deal['id']}/move",
            json={"stage_id": lost_stage["id"]},
            headers=csrf_headers(token),
        )
        assert bare.status_code == 422

        reason = (
            await client.post(
                "/api/lost-reasons",
                json={"name": f"r-{uuid.uuid4().hex[:8]}"},
                headers=csrf_headers(token),
            )
        ).json()
        reason_ids.append(reason["id"])
        lost = await client.post(
            f"/api/deals/{deal['id']}/move",
            json={"stage_id": lost_stage["id"], "lost_reason_id": reason["id"]},
            headers=csrf_headers(token),
        )
        assert lost.status_code == 200
        assert lost.json()["status"] == "lost"
        assert lost.json()["stage_locked"] is True
    finally:
        await purge_contacts(factory, contact_ids)
        await purge_rows(factory, "crm_lost_reasons", reason_ids)
        await engine.dispose()


async def test_bulk_operations(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    tag_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipeline = await default_pipeline(client)
        opens = [s for s in pipeline["stages"] if s["kind"] == "open"]
        target = opens[1] if len(opens) > 1 else opens[0]
        tag = (
            await client.post(
                "/api/tags",
                json={"name": f"b-{uuid.uuid4().hex[:8]}"},
                headers=csrf_headers(token),
            )
        ).json()
        tag_ids.append(tag["id"])
        deal_ids = []
        for _ in range(2):
            contact = await create_contact(client, token, whatsapp_id=_wa())
            contact_ids.append(contact["id"])
            deal = await create_deal(client, token, contact["id"], pipeline)
            deal_ids.append(deal["id"])

        empty = await client.post(
            "/api/deals/bulk", json={"ids": deal_ids}, headers=csrf_headers(token)
        )
        assert empty.status_code == 422

        missing = await client.post(
            "/api/deals/bulk",
            json={
                "ids": deal_ids + ["00000000-0000-0000-0000-000000000000"],
                "set_stage_id": target["id"],
            },
            headers=csrf_headers(token),
        )
        assert missing.status_code == 404
        # All-or-nothing: nothing was applied.
        untouched = await client.get(f"/api/deals/{deal_ids[0]}")
        assert untouched.json()["stage_locked"] is False

        ok = await client.post(
            "/api/deals/bulk",
            json={"ids": deal_ids, "set_stage_id": target["id"], "add_tag_id": tag["id"]},
            headers=csrf_headers(token),
        )
        assert ok.json() == {"updated": 2}
        for deal_id in deal_ids:
            fetched = await client.get(f"/api/deals/{deal_id}")
            assert fetched.json()["stage_locked"] is True
            assert any(t["id"] == tag["id"] for t in fetched.json()["tags"])
    finally:
        await purge_contacts(factory, contact_ids)
        await purge_rows(factory, "crm_tags", tag_ids)
        await engine.dispose()


async def test_deal_visibility_scope(client, settings, app):
    from backend.tests.crm_helpers import ManagerSession, make_manager

    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipeline = await default_pipeline(client)
        owner = await make_manager(client, token)
        stranger = await make_manager(client, token)
        contact = await create_contact(
            client, token, owner_id=owner["user"]["id"], whatsapp_id=_wa()
        )
        contact_ids.append(contact["id"])
        deal = await create_deal(
            client, token, contact["id"], pipeline, owner_id=owner["user"]["id"]
        )

        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO crm_settings (key, value) VALUES"
                    " ('restrict_managers_to_own', 'true')"
                    " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
                )
            )
            await session.commit()
        try:
            async with ManagerSession(app, stranger["email"], stranger["password"]) as mgr:
                assert mgr.client is not None
                assert (await mgr.client.get(f"/api/deals/{deal['id']}")).status_code == 404
                board = await mgr.client.get(f"/api/deals/board?pipeline_id={pipeline['id']}")
                for column in board.json()["columns"]:
                    assert all(i["id"] != deal["id"] for i in column["items"])
        finally:
            async with factory() as session:
                await session.execute(
                    text("DELETE FROM crm_settings WHERE key = 'restrict_managers_to_own'")
                )
                await session.commit()
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()
