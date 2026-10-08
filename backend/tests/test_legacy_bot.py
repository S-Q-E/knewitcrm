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


async def test_legacy_leads_api_is_gone(authed):
    # Legacy /api/leads* had no visibility checks; it was removed (audit C1).
    assert (await authed.get("/api/leads")).status_code == 404
    assert (await authed.get(f"/api/leads/{LEAD_ID}")).status_code == 404
    assert (await authed.get(f"/api/leads/{LEAD_ID}/messages")).status_code == 404
    assert (await authed.get(f"/api/leads/{LEAD_ID}/events")).status_code == 404


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
                "crm_login_attempts",
                "crm_pipelines",
                "crm_stages",
                "crm_contacts",
                "crm_deals",
                "crm_deal_stage_history",
                "crm_notes",
                "crm_saved_views",
                "crm_tasks",
                "crm_notifications",
                "crm_automations",
                "crm_lost_reasons",
                "crm_tags",
                "crm_entity_tags",
                "crm_custom_fields",
                "crm_conversation_state",
                "crm_settings",
                "crm_activity_log",
                "crm_outbox",
                "crm_quick_replies",
                "crm_imports",
            }
            # Bot data untouched.
            count = await conn.execute(text("SELECT COUNT(*) FROM knewit_leads"))
            assert count.scalar() == 6
    finally:
        await engine.dispose()
