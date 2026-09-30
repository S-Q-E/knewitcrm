from __future__ import annotations

import pytest
from sqlalchemy import text

from backend.tests.conftest import login_admin

pytestmark = pytest.mark.usefixtures("db_available")

LEAD_ID = "77010000001@c.us"


@pytest.fixture()
async def authed(client, settings):
    await login_admin(client, settings)
    return client


async def test_leads_list_shape_and_pagination(authed):
    response = await authed.get("/api/leads?limit=2&offset=0")
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["count"] == 2
    first = body["items"][0]
    for key in ("whatsapp_id", "name", "current_stage", "status", "last_message"):
        assert key in first


async def test_leads_search_and_filters(authed):
    by_name = await authed.get("/api/leads?search=айгерим")
    assert by_name.json()["count"] == 1

    by_status = await authed.get("/api/leads?status=ЗАПИСАН")
    items = by_status.json()["items"]
    assert items and all(i["status"] == "ЗАПИСАН" for i in items)

    by_stage = await authed.get("/api/leads?stage=ПРОДАЖА")
    items = by_stage.json()["items"]
    assert items and all(i["current_stage"] == "ПРОДАЖА" for i in items)


async def test_get_lead_and_404(authed):
    ok = await authed.get(f"/api/leads/{LEAD_ID}")
    assert ok.status_code == 200
    assert ok.json()["whatsapp_id"] == LEAD_ID

    missing = await authed.get("/api/leads/unknown@c.us")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


async def test_messages_and_events_contract(authed):
    messages = await authed.get(f"/api/leads/{LEAD_ID}/messages")
    assert messages.status_code == 200
    items = messages.json()["items"]
    assert len(items) >= 3
    assert items[0]["direction"] == "in"
    assert "content" in items[0]

    events = await authed.get(f"/api/leads/{LEAD_ID}/events")
    assert events.status_code == 200
    assert any(e["event_type"] == "stage_entered" for e in events.json()["items"])


async def test_removed_stats_and_funnel(authed):
    assert (await authed.get("/api/stats")).status_code == 404
    assert (await authed.get("/api/funnel")).status_code == 404


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
            assert set(crm_tables) == {
                "crm_users",
                "crm_sessions",
                "crm_pipelines",
                "crm_stages",
                "crm_contacts",
                "crm_deals",
                "crm_deal_stage_history",
                "crm_notes",
                "crm_saved_views",
                "crm_tasks",
                "crm_lost_reasons",
                "crm_tags",
                "crm_entity_tags",
                "crm_custom_fields",
                "crm_conversation_state",
                "crm_settings",
                "crm_activity_log",
            }
            # Bot data untouched.
            count = await conn.execute(text("SELECT COUNT(*) FROM knewit_leads"))
            assert count.scalar() == 6
    finally:
        await engine.dispose()
