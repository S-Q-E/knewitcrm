from __future__ import annotations

import uuid

import pytest

from backend.tests.conftest import csrf_headers
from backend.tests.crm_helpers import (
    ManagerSession,
    admin_csrf,
    assert_logged,
    engine_factory,
    make_manager,
)

pytestmark = pytest.mark.usefixtures("db_available")


async def test_saved_views_crud_and_visibility(client, settings, app):
    engine, factory = engine_factory(settings)
    try:
        token = await admin_csrf(client, settings)
        created = await client.post(
            "/api/saved-views",
            json={"entity": "deal", "name": "Mine", "filters": {"owner_id": "x"}},
            headers=csrf_headers(token),
        )
        assert created.status_code == 201
        view_id = created.json()["id"]
        await assert_logged(factory, "saved_view", view_id, "saved_view_created")

        mine = await client.get("/api/saved-views?entity=deal")
        assert any(v["id"] == view_id for v in mine.json()["items"])

        manager = await make_manager(client, token)
        async with ManagerSession(app, manager["email"], manager["password"]) as mgr:
            assert mgr.client is not None
            # Private admin view is invisible to the manager.
            others = await mgr.client.get("/api/saved-views?entity=deal")
            assert all(v["id"] != view_id for v in others.json()["items"])
            # Manager cannot edit чужое.
            forbidden = await mgr.client.patch(
                f"/api/saved-views/{view_id}",
                json={"name": "Hack"},
                headers=mgr.headers(),
            )
            assert forbidden.status_code == 403
            # Manager cannot share.
            share_forbidden = await mgr.client.post(
                "/api/saved-views",
                json={"entity": "deal", "name": "Shared?", "is_shared": True},
                headers=mgr.headers(),
            )
            assert share_forbidden.status_code == 403
            own = await mgr.client.post(
                "/api/saved-views",
                json={"entity": "deal", "name": "Mgr view", "filters": {}},
                headers=mgr.headers(),
            )
            assert own.status_code == 201
            own_id = own.json()["id"]

        # Admin shares the view; now the manager sees it.
        shared = await client.patch(
            f"/api/saved-views/{view_id}",
            json={"is_shared": True},
            headers=csrf_headers(token),
        )
        assert shared.json()["is_shared"] is True
        async with ManagerSession(app, manager["email"], manager["password"]) as mgr2:
            assert mgr2.client is not None
            visible = await mgr2.client.get("/api/saved-views?entity=deal")
            assert any(v["id"] == view_id for v in visible.json()["items"])
            # Manager still cannot delete the admin's view.
            assert (
                await mgr2.client.delete(f"/api/saved-views/{view_id}", headers=mgr2.headers())
            ).status_code == 403
            # But can delete their own.
            assert (
                await mgr2.client.delete(f"/api/saved-views/{own_id}", headers=mgr2.headers())
            ).status_code == 200

        assert (
            await client.delete(f"/api/saved-views/{view_id}", headers=csrf_headers(token))
        ).status_code == 200
        assert (
            await client.delete(f"/api/saved-views/{view_id}", headers=csrf_headers(token))
        ).status_code == 404
    finally:
        await engine.dispose()


async def test_deals_contact_source_filter(client, settings):
    from backend.tests.crm_helpers import (
        create_contact,
        create_deal,
        default_pipeline,
        purge_contacts,
    )

    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipeline = await default_pipeline(client)
        bot_contact = await create_contact(
            client, token, source="bot", whatsapp_id=f"7999{uuid.uuid4().hex[:8]}@c.us"
        )
        manual_contact = await create_contact(
            client, token, source="manual", whatsapp_id=f"7999{uuid.uuid4().hex[:8]}@c.us"
        )
        contact_ids += [bot_contact["id"], manual_contact["id"]]
        await create_deal(client, token, bot_contact["id"], pipeline, title="SrcBot")
        await create_deal(client, token, manual_contact["id"], pipeline, title="SrcManual")

        filtered = await client.get("/api/deals?contact_source=manual&search=Src")
        titles = [d["title"] for d in filtered.json()["items"]]
        assert "SrcManual" in titles and "SrcBot" not in titles

        board = await client.get(
            f"/api/deals/board?pipeline_id={pipeline['id']}&contact_source=bot&search=Src"
        )
        board_titles = [i["title"] for c in board.json()["columns"] for i in c["items"]]
        assert "SrcBot" in board_titles and "SrcManual" not in board_titles
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()
