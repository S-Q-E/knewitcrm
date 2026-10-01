from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from backend.tests.conftest import csrf_headers
from backend.tests.crm_helpers import (
    admin_csrf,
    create_contact,
    create_deal,
    default_pipeline,
    engine_factory,
    make_manager,
    purge_contacts,
    purge_rows,
)

pytestmark = pytest.mark.usefixtures("db_available")

PERIOD = {"date_from": "2026-02-10", "date_to": "2026-02-20"}


def _wa() -> str:
    return f"7999{uuid.uuid4().hex[:8]}@c.us"


def _q(params: dict) -> str:
    return "&".join(f"{k}={v}" for k, v in params.items())


def _dt(value: str) -> datetime:
    """Fixed UTC timestamp from 'YYYY-MM-DD HH:MM' (asyncpg needs datetime objects)."""
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


async def _seed_fixed_dataset(client, factory, token: str, pipeline: dict) -> dict:
    """Fixed analytics fixture. All bot timestamps are UTC (= ALM - 6h)."""
    stages = pipeline["stages"]
    s1 = next(s for s in stages if s["name"] == "Новый лид")
    s2 = next(s for s in stages if s["name"] == "Выявление потребности")
    assert s1["bot_stage_key"] == "НОВЫЙ_ЛИД"

    manager_a = await make_manager(client, token)
    manager_b = await make_manager(client, token)
    uid_a = manager_a["user"]["id"]
    uid_b = manager_b["user"]["id"]

    reason = (
        await client.post(
            "/api/lost-reasons",
            json={"name": f"price-{uuid.uuid4().hex[:8]}"},
            headers=csrf_headers(token),
        )
    ).json()

    tag = (
        await client.post(
            "/api/tags", json={"name": f"an-{uuid.uuid4().hex[:8]}"}, headers=csrf_headers(token)
        )
    ).json()

    specs = [
        ("whatsapp", uid_a, 100000),
        ("instagram", uid_a, None),
        ("whatsapp", uid_b, 50000),
        ("manual", uid_a, None),
    ]
    contacts, deals, was = [], [], []
    for source, owner, amount in specs:
        wa = _wa()
        contact = await create_contact(client, token, whatsapp_id=wa, source=source, owner_id=owner)
        contacts.append(contact)
        was.append(wa)
        deal = await create_deal(
            client,
            token,
            contact["id"],
            pipeline,
            owner_id=owner,
            **({"amount": amount} if amount else {}),
        )
        deals.append(deal)
    d1, d2, d3, d4 = (d["id"] for d in deals)
    c1, c2, c3, c4 = (c["id"] for c in contacts)
    wa1, wa2, wa3, wa4 = was

    # d1: won with a trial; d3: lost with a reason.
    won = await client.patch(
        f"/api/deals/{d1}", json={"status": "won"}, headers=csrf_headers(token)
    )
    assert won.status_code == 200
    lost = await client.patch(
        f"/api/deals/{d3}",
        json={"status": "lost", "lost_reason_id": reason["id"]},
        headers=csrf_headers(token),
    )
    assert lost.status_code == 200
    for deal_id, tag_id in ((d1, tag["id"]), (d2, tag["id"])):
        tagged = await client.put(
            f"/api/deals/{deal_id}/tags",
            json={"tag_ids": [tag_id]},
            headers=csrf_headers(token),
        )
        assert tagged.status_code == 200

    t1 = (
        await client.post(
            "/api/tasks",
            json={"title": "Done task", "type": "call", "assignee_id": uid_a, "deal_id": d2},
            headers=csrf_headers(token),
        )
    ).json()
    t2 = (
        await client.post(
            "/api/tasks",
            json={
                "title": "Overdue task",
                "type": "call",
                "assignee_id": uid_a,
                "due_at": "2026-02-15T04:00:00Z",
            },
            headers=csrf_headers(token),
        )
    ).json()
    done = await client.post(f"/api/tasks/{t1['id']}/done", headers=csrf_headers(token))
    assert done.status_code == 200

    async with factory() as session:
        await session.execute(
            text("UPDATE crm_deals SET created_at = :at WHERE id = :id"),
            [
                {"at": _dt("2026-02-11 04:00"), "id": d1},
                {"at": _dt("2026-02-11 06:00"), "id": d2},
                {"at": _dt("2026-02-12 02:00"), "id": d3},
                {"at": _dt("2026-02-13 01:00"), "id": d4},
            ],
        )
        await session.execute(
            text("UPDATE crm_contacts SET created_at = :at WHERE id = :id"),
            [
                {"at": _dt("2026-02-11 03:30"), "id": c1},
                {"at": _dt("2026-02-11 05:30"), "id": c2},
                {"at": _dt("2026-02-12 01:30"), "id": c3},
                {"at": _dt("2026-02-13 00:30"), "id": c4},
            ],
        )
        await session.execute(
            text("UPDATE crm_deals SET trial_at = :at, closed_at = :closed WHERE id = :id"),
            {"at": _dt("2026-02-12 04:00"), "closed": _dt("2026-02-13 05:00"), "id": d1},
        )
        await session.execute(
            text("UPDATE crm_deals SET closed_at = :closed, stage_id = :stage WHERE id = :id"),
            {"closed": _dt("2026-02-14 03:00"), "stage": s2["id"], "id": d3},
        )
        await session.execute(
            text("UPDATE crm_deals SET stage_id = :stage WHERE id = :id"),
            {"stage": s2["id"], "id": d4},
        )
        # Exact stage history; d4 keeps none (fallback branch).
        await session.execute(
            text("DELETE FROM crm_deal_stage_history WHERE deal_id = ANY(:ids)"),
            {"ids": [d1, d2, d3, d4]},
        )
        for deal_id, from_id, to_id, at in (
            (d1, None, s1["id"], _dt("2026-02-11 04:00")),
            (d1, s1["id"], s2["id"], _dt("2026-02-12 04:00")),
            (d2, None, s1["id"], _dt("2026-02-11 06:00")),
            (d3, None, s1["id"], _dt("2026-02-12 02:00")),
            (d3, s1["id"], s2["id"], _dt("2026-02-13 02:00")),
        ):
            await session.execute(
                text(
                    "INSERT INTO crm_deal_stage_history"
                    " (id, deal_id, from_stage_id, to_stage_id, source, at)"
                    " VALUES (:id, :deal, :from, :to, 'manager', :at)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "deal": deal_id,
                    "from": from_id,
                    "to": to_id,
                    "at": at,
                },
            )
        await session.execute(
            text("UPDATE crm_tasks SET done_at = :at WHERE id = :id"),
            {"at": _dt("2026-02-15 05:00"), "id": t1["id"]},
        )
        for wa, stage, status, objection, created in (
            (wa1, "ПРОДАЖА", "КЛИЕНТ", "Дорого", _dt("2026-02-11 03:00")),
            (wa2, "НОВЫЙ_ЛИД", "ACTIVE", None, _dt("2026-02-11 05:00")),
            (wa3, "РАБОТА_С_ВОЗРАЖЕНИЕМ", "МЕНЕДЖЕР", "Дорого", _dt("2026-02-12 01:00")),
            (wa4, "НОВЫЙ_ЛИД", "ОТКАЗ", "Не отвечает", _dt("2026-02-12 06:00")),
        ):
            await session.execute(
                text(
                    "INSERT INTO knewit_leads"
                    " (whatsapp_id, name, current_stage, status, last_objection,"
                    " created_at, updated_at)"
                    " VALUES (:wa, 'Bot Lead', :stage, :status, :obj, :at, :at)"
                ),
                {"wa": wa, "stage": stage, "status": status, "obj": objection, "at": created},
            )
        for wa, direction, tokens, rt, created in (
            (wa1, "in", 120, None, _dt("2026-02-11 03:00")),
            (wa1, "out", 60, 5000, _dt("2026-02-11 03:05")),
            (wa2, "in", 40, None, _dt("2026-02-11 05:00")),
            (wa3, "in", 70, None, _dt("2026-02-12 01:00")),
            (wa3, "out", 30, 3000, _dt("2026-02-12 01:02")),
            (wa4, "in", 25, None, _dt("2026-02-12 06:00")),
        ):
            await session.execute(
                text(
                    "INSERT INTO knewit_messages"
                    " (whatsapp_id, direction, message_type, content, tokens_used,"
                    " response_time_ms, created_at)"
                    " VALUES (:wa, :dir, 'chat', 'hi', :tokens, :rt, :at)"
                ),
                {"wa": wa, "dir": direction, "tokens": tokens, "rt": rt, "at": created},
            )
        await session.execute(
            text(
                "INSERT INTO knewit_events"
                " (whatsapp_id, event_type, from_stage, to_stage, created_at)"
                " VALUES (:wa, 'transferred_to_manager', 'РАБОТА_С_ВОЗРАЖЕНИЕМ',"
                " 'МЕНЕДЖЕР', '2026-02-12 01:05+00')"
            ),
            {"wa": wa3},
        )
        await session.commit()
    return {
        "uid_a": uid_a,
        "uid_b": uid_b,
        "reason": reason,
        "tag": tag,
        "contacts": [c1, c2, c3, c4],
        "tasks": [t1["id"], t2["id"]],
        "s1": s1,
        "s2": s2,
    }


async def _overview(client, params: dict):
    response = await client.get(f"/api/analytics/overview?{_q(params)}")
    assert response.status_code == 200, response.text
    return response.json()


async def test_overview_matches_hand_computed_values(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    extra_ids: dict[str, list[str]] = {"reasons": [], "tags": [], "tasks": []}
    try:
        token = await admin_csrf(client, settings)
        pipeline = await default_pipeline(client)
        seed = await _seed_fixed_dataset(client, factory, token, pipeline)
        contact_ids.extend(seed["contacts"])
        extra_ids["reasons"].append(seed["reason"]["id"])
        extra_ids["tags"].append(seed["tag"]["id"])
        extra_ids["tasks"].extend(seed["tasks"])

        data = await _overview(client, PERIOD)
        assert data["meta"]["date_from"] == "2026-02-10"
        assert data["meta"]["date_to"] == "2026-02-20"
        assert data["meta"]["currency"] == "KZT"

        funnel = data["funnel"]
        assert funnel["cohort_deals"] == 4
        by_name = {s["name"]: s for s in funnel["stages"]}
        assert by_name["Новый лид"]["reached"] == 3
        assert by_name["Выявление потребности"]["reached"] == 3
        assert by_name["Выявление потребности"]["conversion_from_prev"] == 1.0
        assert by_name["Новый лид"]["conversion_from_prev"] is None
        assert by_name["Новый лид"]["avg_hours_on_stage"] == 24.0
        assert by_name["Выявление потребности"]["is_bottleneck"] is True
        assert funnel["total_entered"] == 3
        assert funnel["total_finished"] == 1
        assert funnel["overall_conversion"] == pytest.approx(1 / 3, abs=0.001)

        summary = data["summary"]
        assert summary["new_leads"] == 4
        assert summary["trials_booked"] == 1
        assert summary["won_count"] == 1
        assert summary["won_sum"] == 100000.0
        assert summary["avg_check"] == 100000.0
        assert summary["lost_count"] == 1
        assert summary["lost_by_reason"] == [
            {"reason_id": seed["reason"]["id"], "reason": seed["reason"]["name"], "count": 1}
        ]
        buckets = {b["bucket"]: b for b in summary["dynamics"]}
        assert len(summary["dynamics"]) == 11
        assert buckets["2026-02-11"]["new_leads"] == 2
        assert buckets["2026-02-12"] == {
            "bucket": "2026-02-12",
            "new_leads": 2,
            "trials": 1,
            "won": 0,
            "won_sum": 0.0,
            "lost": 0,
        }
        assert buckets["2026-02-13"]["won"] == 1
        assert buckets["2026-02-13"]["won_sum"] == 100000.0
        assert buckets["2026-02-14"]["lost"] == 1

        managers = {m["user_id"]: m for m in data["managers"]}
        row_a = managers[seed["uid_a"]]
        assert row_a["deals_in_work"] == 2
        assert (row_a["won"], row_a["lost"]) == (1, 0)
        assert row_a["conversion"] == 1.0
        assert row_a["won_sum"] == 100000.0
        assert row_a["avg_first_response_hours"] == pytest.approx(5 / 60, abs=0.01)
        assert row_a["tasks_done"] == 1
        assert row_a["tasks_overdue"] == 1
        row_b = managers[seed["uid_b"]]
        assert (row_b["won"], row_b["lost"]) == (0, 1)
        assert row_b["conversion"] == 0.0
        assert row_b["avg_first_response_hours"] == pytest.approx(2 / 60, abs=0.01)

        bot = data["bot"]
        assert (bot["messages_in"], bot["messages_out"]) == (4, 2)
        assert bot["avg_response_time_ms"] == 4000.0
        assert bot["tokens_total"] == 345
        assert bot["handover_count"] == 1
        assert bot["handover_share"] == 0.25
        assert bot["closed_without_manager"] == 3
        assert bot["closed_without_manager_share"] == 0.75
        assert bot["top_objections"][0] == {"objection": "Дорого", "count": 2}
        assert sum(r["count"] for r in bot["abandoned_by_stage"]) == 4

        sources = {s["source"]: s for s in data["sources"]}
        assert sources["whatsapp"]["contacts"] == 2
        assert sources["whatsapp"]["won"] == 1
        assert sources["whatsapp"]["won_sum"] == 100000.0
        assert sources["instagram"]["contacts"] == 1
        tags = {t["tag"]: t for t in data["tags"]}
        assert tags[seed["tag"]["name"]]["deals"] == 2
        assert tags[seed["tag"]["name"]]["won"] == 1
    finally:
        await purge_contacts(factory, contact_ids)
        await purge_rows(factory, "crm_tasks", extra_ids["tasks"])
        await purge_rows(factory, "crm_tags", extra_ids["tags"])
        await purge_rows(factory, "crm_lost_reasons", extra_ids["reasons"])
        await engine.dispose()


async def test_empty_period_and_deals_without_history(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipeline = await default_pipeline(client)
        contact = await create_contact(client, token, whatsapp_id=_wa())
        contact_ids.append(contact["id"])
        deal = await create_deal(client, token, contact["id"], pipeline)
        async with factory() as session:
            await session.execute(
                text("DELETE FROM crm_deal_stage_history WHERE deal_id = :id"), {"id": deal["id"]}
            )
            await session.commit()

        data = await _overview(client, {"date_from": "2020-01-01", "date_to": "2020-01-02"})
        assert data["funnel"]["cohort_deals"] == 0
        assert data["funnel"]["overall_conversion"] is None
        assert all(s["reached"] == 0 for s in data["funnel"]["stages"])
        summary = data["summary"]
        assert summary["new_leads"] == 0
        assert summary["won_count"] == 0
        assert summary["avg_check"] == 0
        assert summary["dynamics"] != []
        assert all(b["new_leads"] == 0 for b in summary["dynamics"])
        assert data["bot"]["handover_share"] is None
        assert data["bot"]["closed_without_manager_share"] is None
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_owner_filter_and_weekly_granularity(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipeline = await default_pipeline(client)
        seed = await _seed_fixed_dataset(client, factory, token, pipeline)
        contact_ids.extend(seed["contacts"])
        try:
            data = await _overview(client, {**PERIOD, "owner_id": seed["uid_a"]})
            assert data["meta"]["owner_id"] == seed["uid_a"]
            assert data["funnel"]["cohort_deals"] == 3
            assert data["summary"]["new_leads"] == 3
            assert [m["user_id"] for m in data["managers"]] == [seed["uid_a"]]

            weekly = await _overview(client, {**PERIOD, "granularity": "week"})
            assert [b["bucket"] for b in weekly["summary"]["dynamics"]] == [
                "2026-02-10",
                "2026-02-17",
            ]
            assert sum(b["new_leads"] for b in weekly["summary"]["dynamics"]) == 4
        finally:
            await purge_rows(factory, "crm_tasks", seed["tasks"])
            await purge_rows(factory, "crm_tags", [seed["tag"]["id"]])
            await purge_rows(factory, "crm_lost_reasons", [seed["reason"]["id"]])
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_validation_auth_and_export(client, settings, app):
    from backend.tests.crm_helpers import ManagerSession, make_manager

    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipeline = await default_pipeline(client)
        seed = await _seed_fixed_dataset(client, factory, token, pipeline)
        contact_ids.extend(seed["contacts"])
        try:
            bad_date = await client.get("/api/analytics/overview?date_from=not-a-date")
            assert bad_date.status_code == 422
            assert bad_date.json()["error"]["code"] == "INVALID_PERIOD"
            swapped = await client.get(
                "/api/analytics/overview?date_from=2026-02-20&date_to=2026-02-10"
            )
            assert swapped.json()["error"]["code"] == "INVALID_PERIOD"
            huge = await client.get(
                "/api/analytics/overview?date_from=2020-01-01&date_to=2022-01-01"
            )
            assert huge.json()["error"]["code"] == "PERIOD_TOO_LARGE"
            unknown = await client.get(
                "/api/analytics/overview?pipeline_id=00000000-0000-0000-0000-000000000000"
            )
            assert unknown.status_code == 404
            bad_owner = await client.get(
                "/api/analytics/overview?owner_id=00000000-0000-0000-0000-000000000000"
            )
            assert bad_owner.json()["error"]["code"] == "UNKNOWN_OWNER"

            export = await client.get(f"/api/analytics/export?section=funnel&{_q(PERIOD)}")
            assert export.status_code == 200
            assert "text/csv" in export.headers["content-type"]
            body = export.text
            assert "stage_id" in body.splitlines()[0]
            assert "Новый лид" in body
            dyn = await client.get(f"/api/analytics/export?section=dynamics&{_q(PERIOD)}")
            assert len(dyn.text.splitlines()) == 12  # header + 11 day buckets

            # Restriction forces managers onto their own scope (404 for чужое).
            manager = await make_manager(client, token)
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
                async with ManagerSession(app, manager["email"], manager["password"]) as mgr:
                    assert mgr.client is not None
                    own = await mgr.client.get(f"/api/analytics/overview?{_q(PERIOD)}")
                    assert own.status_code == 200
                    assert own.json()["meta"]["owner_id"] == manager["user"]["id"]
                    foreign = await mgr.client.get(
                        f"/api/analytics/overview?{_q(PERIOD)}&owner_id={seed['uid_a']}"
                    )
                    assert foreign.status_code == 404
            finally:
                async with factory() as session:
                    await session.execute(
                        text("DELETE FROM crm_settings WHERE key = 'restrict_managers_to_own'")
                    )
                    await session.commit()
        finally:
            await purge_rows(factory, "crm_tasks", seed["tasks"])
            await purge_rows(factory, "crm_tags", [seed["tag"]["id"]])
            await purge_rows(factory, "crm_lost_reasons", [seed["reason"]["id"]])
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()
