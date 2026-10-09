from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from backend.tests.conftest import csrf_headers
from backend.tests.crm_helpers import (
    ManagerSession,
    admin_csrf,
    assert_logged,
    create_contact,
    create_deal,
    default_pipeline,
    engine_factory,
    make_manager,
    purge_contacts,
    purge_pipelines,
)

pytestmark = pytest.mark.usefixtures("db_available")


async def test_admin_pipeline_crud(client, settings):
    engine, factory = engine_factory(settings)
    try:
        token = await admin_csrf(client, settings)
        created = await client.post(
            "/api/pipelines",
            json={"name": f"Pipe {uuid.uuid4().hex[:8]}"},
            headers=csrf_headers(token),
        )
        assert created.status_code == 201, created.text
        pipeline = created.json()
        pipeline_id = pipeline["id"]

        stage = await client.post(
            f"/api/pipelines/{pipeline_id}/stages",
            json={"name": "First", "kind": "open"},
            headers=csrf_headers(token),
        )
        assert stage.status_code == 201
        stage_b = await client.post(
            f"/api/pipelines/{pipeline_id}/stages",
            json={"name": "Second", "kind": "open"},
            headers=csrf_headers(token),
        )
        assert stage_b.status_code == 201

        reordered = await client.post(
            f"/api/pipelines/{pipeline_id}/stages/reorder",
            json={"ordered_ids": [stage_b.json()["id"], stage.json()["id"]]},
            headers=csrf_headers(token),
        )
        assert reordered.status_code == 200
        assert [s["name"] for s in reordered.json()] == ["Second", "First"]

        renamed = await client.patch(
            f"/api/pipelines/{pipeline_id}",
            json={"name": pipeline["name"] + " v2"},
            headers=csrf_headers(token),
        )
        assert renamed.status_code == 200

        # Pipeline with stages cannot be deleted.
        blocked = await client.delete(f"/api/pipelines/{pipeline_id}", headers=csrf_headers(token))
        assert blocked.status_code == 409

        await assert_logged(factory, "pipeline", pipeline_id, "pipeline_created")

        for stage_id in (stage.json()["id"], stage_b.json()["id"]):
            gone = await client.delete(f"/api/stages/{stage_id}", headers=csrf_headers(token))
            assert gone.status_code == 200
        gone_pipe = await client.delete(
            f"/api/pipelines/{pipeline_id}", headers=csrf_headers(token)
        )
        assert gone_pipe.status_code == 200
    finally:
        await engine.dispose()


async def test_stage_delete_moves_deals_with_recipient(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    pipeline_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        created = await client.post(
            "/api/pipelines",
            json={"name": f"Doomed pipe {uuid.uuid4().hex[:8]}"},
            headers=csrf_headers(token),
        )
        assert created.status_code == 201
        pipe = created.json()
        pipeline_ids.append(pipe["id"])
        donor = (
            await client.post(
                f"/api/pipelines/{pipe['id']}/stages",
                json={"name": "Donor"},
                headers=csrf_headers(token),
            )
        ).json()
        recipient = (
            await client.post(
                f"/api/pipelines/{pipe['id']}/stages",
                json={"name": "Recipient"},
                headers=csrf_headers(token),
            )
        ).json()
        contact = await create_contact(
            client, token, whatsapp_id=f"7999{uuid.uuid4().hex[:8]}@c.us"
        )
        contact_ids.append(contact["id"])
        deal = await create_deal(
            client,
            token,
            contact["id"],
            {**pipe, "stages": [donor]},
            stage_id=donor["id"],
            pipeline_id=pipe["id"],
            title="Doomed",
        )

        blocked = await client.delete(f"/api/stages/{donor['id']}", headers=csrf_headers(token))
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "STAGE_HAS_DEALS"

        moved = await client.delete(
            f"/api/stages/{donor['id']}?to_stage_id={recipient['id']}",
            headers=csrf_headers(token),
        )
        assert moved.status_code == 200
        assert moved.json()["moved_deals"] == 1

        fetched = await client.get(f"/api/deals/{deal['id']}")
        assert fetched.json()["stage_id"] == recipient["id"]
    finally:
        await purge_contacts(factory, contact_ids)
        await purge_pipelines(factory, pipeline_ids)
        await engine.dispose()


async def test_manager_cannot_mutate_funnel(client, settings, app):
    token = await admin_csrf(client, settings)
    manager = await make_manager(client, token)
    async with ManagerSession(app, manager["email"], manager["password"]) as mgr:
        assert mgr.client is not None
        forbidden = await mgr.client.post(
            "/api/pipelines", json={"name": "Hack"}, headers=mgr.headers()
        )
        assert forbidden.status_code == 403

        pipeline = await default_pipeline(client)
        forbidden_stage = await mgr.client.post(
            f"/api/pipelines/{pipeline['id']}/stages",
            json={"name": "Hack stage"},
            headers=mgr.headers(),
        )
        assert forbidden_stage.status_code == 403

        allowed = await mgr.client.get("/api/pipelines")
        assert allowed.status_code == 200
        assert allowed.json(), "managers must read the funnel for the board"


async def test_reorder_validates_ids(client, settings):
    token = await admin_csrf(client, settings)
    pipeline = await default_pipeline(client)
    bad = await client.post(
        f"/api/pipelines/{pipeline['id']}/stages/reorder",
        json={"ordered_ids": [pipeline["stages"][0]["id"]]},
        headers=csrf_headers(token),
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "STAGE_MISMATCH"


async def test_duplicate_names_rejected(client, settings):
    token = await admin_csrf(client, settings)
    name = f"Pipe {uuid.uuid4().hex[:8]}"
    first = await client.post("/api/pipelines", json={"name": name}, headers=csrf_headers(token))
    assert first.status_code == 201
    pipeline_id = first.json()["id"]
    try:
        dup = await client.post("/api/pipelines", json={"name": name}, headers=csrf_headers(token))
        assert dup.status_code == 409

        stage = await client.post(
            f"/api/pipelines/{pipeline_id}/stages",
            json={"name": "Same"},
            headers=csrf_headers(token),
        )
        assert stage.status_code == 201
        dup_stage = await client.post(
            f"/api/pipelines/{pipeline_id}/stages",
            json={"name": "Same"},
            headers=csrf_headers(token),
        )
        assert dup_stage.status_code == 409
    finally:
        engine, factory = engine_factory(settings)
        try:
            await purge_pipelines(factory, [pipeline_id])
        finally:
            await engine.dispose()


async def test_delete_stage_counts_and_moves_soft_deleted_deals(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    pipeline_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        pipe = (
            await client.post(
                "/api/pipelines",
                json={"name": f"Trash stage {uuid.uuid4().hex[:8]}"},
                headers=csrf_headers(token),
            )
        ).json()
        pipeline_ids.append(pipe["id"])
        donor = (
            await client.post(
                f"/api/pipelines/{pipe['id']}/stages",
                json={"name": "Donor"},
                headers=csrf_headers(token),
            )
        ).json()
        recipient = (
            await client.post(
                f"/api/pipelines/{pipe['id']}/stages",
                json={"name": "Recipient"},
                headers=csrf_headers(token),
            )
        ).json()
        contact = await create_contact(
            client, token, whatsapp_id=f"7999{uuid.uuid4().hex[:8]}@c.us"
        )
        contact_ids.append(contact["id"])
        deal = await create_deal(
            client,
            token,
            contact["id"],
            {**pipe, "stages": [donor]},
            stage_id=donor["id"],
            pipeline_id=pipe["id"],
            title="Trashed",
        )
        trashed = await client.delete(f"/api/deals/{deal['id']}", headers=csrf_headers(token))
        assert trashed.status_code == 200, trashed.text

        blocked = await client.delete(f"/api/stages/{donor['id']}", headers=csrf_headers(token))
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["error"]["code"] == "STAGE_HAS_DEALS"
        assert blocked.json()["error"]["details"]["deals"] == 1

        moved = await client.delete(
            f"/api/stages/{donor['id']}?to_stage_id={recipient['id']}",
            headers=csrf_headers(token),
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["moved_deals"] == 1
        async with factory() as session:
            stage_now = (
                await session.execute(
                    text("SELECT stage_id::text FROM crm_deals WHERE id = :id"),
                    {"id": deal["id"]},
                )
            ).scalar_one()
        assert stage_now == recipient["id"]
    finally:
        await purge_contacts(factory, contact_ids)
        await purge_pipelines(factory, pipeline_ids)
        await engine.dispose()
