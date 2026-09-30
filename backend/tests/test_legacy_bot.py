from __future__ import annotations

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.usefixtures("db_available")

LEAD_ID = "77010000001@c.us"


async def test_stats_contract(client, auth_headers):
    response = await client.get("/api/stats", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["leads"]["total"] == 6
    assert body["leads"]["active"] == 1
    assert body["leads"]["booked"] == 1
    assert body["leads"]["clients"] == 1
    assert {s["stage"] for s in body["stages"]} >= {"НОВЫЙ_ЛИД", "ЗАПИСЬ", "ПРОДАЖА"}
    assert body["messages_24h"]["incoming"] >= 1
    assert body["messages_24h"]["outgoing"] >= 1


async def test_leads_list_shape_and_pagination(client, auth_headers):
    response = await client.get("/api/leads?limit=2&offset=0", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["count"] == 2
    first = body["items"][0]
    for key in ("whatsapp_id", "name", "current_stage", "status", "last_message"):
        assert key in first


async def test_leads_search_and_filters(client, auth_headers):
    by_name = await client.get("/api/leads?search=айгерим", headers=auth_headers)
    assert by_name.json()["count"] == 1

    by_status = await client.get("/api/leads?status=ЗАПИСАН", headers=auth_headers)
    items = by_status.json()["items"]
    assert items and all(i["status"] == "ЗАПИСАН" for i in items)

    by_stage = await client.get("/api/leads?stage=ПРОДАЖА", headers=auth_headers)
    items = by_stage.json()["items"]
    assert items and all(i["current_stage"] == "ПРОДАЖА" for i in items)


async def test_get_lead_and_404(client, auth_headers):
    ok = await client.get(f"/api/leads/{LEAD_ID}", headers=auth_headers)
    assert ok.status_code == 200
    assert ok.json()["whatsapp_id"] == LEAD_ID

    missing = await client.get("/api/leads/unknown@c.us", headers=auth_headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


async def test_messages_and_events_contract(client, auth_headers):
    messages = await client.get(f"/api/leads/{LEAD_ID}/messages", headers=auth_headers)
    assert messages.status_code == 200
    items = messages.json()["items"]
    assert len(items) >= 3
    assert items[0]["direction"] == "in"
    assert "content" in items[0]

    events = await client.get(f"/api/leads/{LEAD_ID}/events", headers=auth_headers)
    assert events.status_code == 200
    assert any(e["event_type"] == "stage_entered" for e in events.json()["items"])


async def test_funnel_contract(client, auth_headers):
    response = await client.get("/api/funnel", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert any(s["stage"] == "ЗАПИСЬ" for s in body["from_events"])
    assert any(s["stage"] == "ПРОДАЖА" for s in body["from_leads"])


async def test_legacy_frontend_still_served(client, auth_headers):
    response = await client.get("/", headers=auth_headers)
    assert response.status_code == 200
    assert "KnewIT CRM" in response.text


async def test_migrate_creates_only_version_table(settings):
    import asyncio

    from alembic import command
    from alembic.config import Config
    from sqlalchemy.ext.asyncio import create_async_engine

    from backend.tests.conftest import REPO_ROOT

    cfg = Config(str(REPO_ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "backend" / "alembic"))
    # env.py calls asyncio.run(), which needs a thread without a running loop.
    await asyncio.to_thread(command.upgrade, cfg, "head")

    engine = create_async_engine(settings.sqlalchemy_url, connect_args=settings.connect_args)
    try:
        async with engine.connect() as conn:
            tables = (
                (
                    await conn.execute(
                        text(
                            "SELECT tablename FROM pg_tables "
                            "WHERE schemaname = 'public' ORDER BY tablename"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert "crm_alembic_version" in tables
            crm_tables = [t for t in tables if t.startswith("crm_") and t != "crm_alembic_version"]
            assert crm_tables == []
            # Bot data untouched.
            count = await conn.execute(text("SELECT COUNT(*) FROM knewit_leads"))
            assert count.scalar() == 6
    finally:
        await engine.dispose()
