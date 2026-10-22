from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

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
)

pytestmark = pytest.mark.usefixtures("db_available")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Same three statements as migration 0021_sync_owner (D40). Kept in sync
# explicitly, as the 0020 backfill test does, so the data rules stay covered.
MIGRATION_SQL = (
    "WITH managed AS ("
    " SELECT DISTINCT ON (d.contact_id) d.id AS deal_id, d.contact_id"
    " FROM crm_deals d"
    " WHERE d.deleted_at IS NULL"
    " ORDER BY d.contact_id, d.updated_at DESC, d.id"
    ")"
    " UPDATE crm_deals d"
    " SET owner_id = COALESCE(s.assigned_to, c.owner_id)"
    " FROM managed m"
    " JOIN crm_contacts c ON c.id = m.contact_id"
    " LEFT JOIN crm_conversation_state s ON s.whatsapp_id = c.whatsapp_id"
    " WHERE d.id = m.deal_id"
    " AND d.owner_id IS NULL"
    " AND COALESCE(s.assigned_to, c.owner_id) IS NOT NULL",
    "WITH managed AS ("
    " SELECT DISTINCT ON (d.contact_id) d.contact_id, d.owner_id"
    " FROM crm_deals d"
    " WHERE d.deleted_at IS NULL"
    " ORDER BY d.contact_id, d.updated_at DESC, d.id"
    ")"
    " UPDATE crm_contacts c"
    " SET owner_id = m.owner_id"
    " FROM managed m"
    " WHERE m.contact_id = c.id AND m.owner_id IS NOT NULL"
    " AND c.owner_id IS DISTINCT FROM m.owner_id",
    "WITH managed AS ("
    " SELECT DISTINCT ON (d.contact_id) d.contact_id, d.owner_id"
    " FROM crm_deals d"
    " WHERE d.deleted_at IS NULL"
    " ORDER BY d.contact_id, d.updated_at DESC, d.id"
    ")"
    " UPDATE crm_conversation_state s"
    " SET assigned_to = m.owner_id"
    " FROM managed m"
    " JOIN crm_contacts c ON c.id = m.contact_id"
    " WHERE s.whatsapp_id = c.whatsapp_id AND m.owner_id IS NOT NULL"
    " AND s.assigned_to IS DISTINCT FROM m.owner_id",
)


def _wa() -> str:
    return f"7999{uuid.uuid4().hex[:8]}@c.us"


async def _insert_lead(factory, wa: str) -> None:
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO knewit_leads (whatsapp_id, name, current_stage, status)"
                " VALUES (:wa, 'Owner Bot', 'НОВЫЙ_ЛИД', 'ACTIVE')"
            ),
            {"wa": wa},
        )
        await session.commit()


async def _owners(factory, contact_id: str, wa: str) -> dict:
    async with factory() as session:
        contact_owner = (
            await session.execute(
                text("SELECT owner_id FROM crm_contacts WHERE id = :id"),
                {"id": contact_id},
            )
        ).scalar_one()
        deal_owner = (
            await session.execute(
                text(
                    "SELECT owner_id FROM crm_deals"
                    " WHERE contact_id = :id AND deleted_at IS NULL"
                    " ORDER BY updated_at DESC, id LIMIT 1"
                ),
                {"id": contact_id},
            )
        ).scalar_one_or_none()
        state = (
            await session.execute(
                text("SELECT assigned_to FROM crm_conversation_state WHERE whatsapp_id = :wa"),
                {"wa": wa},
            )
        ).one_or_none()
    return {
        "contact": str(contact_owner) if contact_owner else None,
        "deal": str(deal_owner) if deal_owner else None,
        "state": str(state[0]) if state is not None and state[0] else None,
        "state_exists": state is not None,
    }


async def test_deal_owner_syncs_contact_and_dialog(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        manager = await make_manager(client, token)
        wa = _wa()
        await _insert_lead(factory, wa)
        pipeline = await default_pipeline(client)
        contact = await create_contact(client, token, whatsapp_id=wa)
        contact_ids.append(contact["id"])
        deal = await create_deal(client, token, contact["id"], pipeline)

        response = await client.patch(
            f"/api/deals/{deal['id']}",
            json={"owner_id": manager["user"]["id"]},
            headers=csrf_headers(token),
        )
        assert response.status_code == 200, response.text
        assert response.json()["owner_id"] == manager["user"]["id"]

        owners = await _owners(factory, contact["id"], wa)
        assert owners["deal"] == manager["user"]["id"]
        assert owners["contact"] == manager["user"]["id"]
        assert owners["state_exists"] is True
        assert owners["state"] == manager["user"]["id"]
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_deal_owner_reset_clears_contact_and_dialog(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        manager = await make_manager(client, token)
        wa = _wa()
        await _insert_lead(factory, wa)
        pipeline = await default_pipeline(client)
        contact = await create_contact(client, token, whatsapp_id=wa)
        contact_ids.append(contact["id"])
        deal = await create_deal(client, token, contact["id"], pipeline)

        assigned = await client.patch(
            f"/api/deals/{deal['id']}",
            json={"owner_id": manager["user"]["id"]},
            headers=csrf_headers(token),
        )
        assert assigned.status_code == 200, assigned.text

        cleared = await client.patch(
            f"/api/deals/{deal['id']}",
            json={"owner_id": None},
            headers=csrf_headers(token),
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["owner_id"] is None

        owners = await _owners(factory, contact["id"], wa)
        assert owners["deal"] is None
        assert owners["contact"] is None
        assert owners["state"] is None
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_bulk_deal_owner_syncs_all(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        manager = await make_manager(client, token)
        pipeline = await default_pipeline(client)
        prepared: list[tuple[dict, dict, str]] = []
        for _ in range(2):
            wa = _wa()
            await _insert_lead(factory, wa)
            contact = await create_contact(client, token, whatsapp_id=wa)
            contact_ids.append(contact["id"])
            deal = await create_deal(client, token, contact["id"], pipeline)
            prepared.append((contact, deal, wa))

        deal_ids = [deal["id"] for _, deal, _ in prepared]
        assigned = await client.post(
            "/api/deals/bulk",
            json={"ids": deal_ids, "set_owner_id": manager["user"]["id"]},
            headers=csrf_headers(token),
        )
        assert assigned.status_code == 200, assigned.text
        for contact, _, wa in prepared:
            owners = await _owners(factory, contact["id"], wa)
            assert owners["deal"] == manager["user"]["id"]
            assert owners["contact"] == manager["user"]["id"]
            assert owners["state"] == manager["user"]["id"]

        unassigned = await client.post(
            "/api/deals/bulk",
            json={"ids": deal_ids, "unassign_owner": True},
            headers=csrf_headers(token),
        )
        assert unassigned.status_code == 200, unassigned.text
        for contact, _, wa in prepared:
            owners = await _owners(factory, contact["id"], wa)
            assert owners["deal"] is None
            assert owners["contact"] is None
            assert owners["state"] is None
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_dialog_assignee_syncs_deal_and_contact(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        manager = await make_manager(client, token)
        wa = _wa()
        await _insert_lead(factory, wa)
        pipeline = await default_pipeline(client)
        contact = await create_contact(client, token, whatsapp_id=wa)
        contact_ids.append(contact["id"])
        deal = await create_deal(client, token, contact["id"], pipeline)

        response = await client.patch(
            f"/api/dialogs/{wa}",
            json={"assigned_to": manager["user"]["id"]},
            headers=csrf_headers(token),
        )
        assert response.status_code == 200, response.text
        assert response.json()["assigned_to"] == manager["user"]["id"]

        owners = await _owners(factory, contact["id"], wa)
        assert owners["deal"] == manager["user"]["id"]
        assert owners["contact"] == manager["user"]["id"]
        assert owners["state"] == manager["user"]["id"]
        fetched = await client.get(f"/api/deals/{deal['id']}")
        assert fetched.json()["owner_id"] == manager["user"]["id"]
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_contact_owner_syncs_deal_and_dialog(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        manager = await make_manager(client, token)
        wa = _wa()
        await _insert_lead(factory, wa)
        pipeline = await default_pipeline(client)
        contact = await create_contact(client, token, whatsapp_id=wa)
        contact_ids.append(contact["id"])
        deal = await create_deal(client, token, contact["id"], pipeline)

        response = await client.patch(
            f"/api/contacts/{contact['id']}",
            json={"owner_id": manager["user"]["id"]},
            headers=csrf_headers(token),
        )
        assert response.status_code == 200, response.text
        assert response.json()["owner_id"] == manager["user"]["id"]

        owners = await _owners(factory, contact["id"], wa)
        assert owners["deal"] == manager["user"]["id"]
        assert owners["contact"] == manager["user"]["id"]
        assert owners["state"] == manager["user"]["id"]
        fetched = await client.get(f"/api/deals/{deal['id']}")
        assert fetched.json()["owner_id"] == manager["user"]["id"]
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_deal_owner_without_bot_lead_skips_conversation_state(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        manager = await make_manager(client, token)
        wa = _wa()
        pipeline = await default_pipeline(client)
        contact = await create_contact(client, token, whatsapp_id=wa)
        contact_ids.append(contact["id"])
        deal = await create_deal(client, token, contact["id"], pipeline)

        response = await client.patch(
            f"/api/deals/{deal['id']}",
            json={"owner_id": manager["user"]["id"]},
            headers=csrf_headers(token),
        )
        assert response.status_code == 200, response.text

        owners = await _owners(factory, contact["id"], wa)
        assert owners["deal"] == manager["user"]["id"]
        assert owners["contact"] == manager["user"]["id"]
        assert owners["state_exists"] is False
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_migration_aligns_old_owners(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        first = await make_manager(client, token)
        second = await make_manager(client, token)
        pipeline = await default_pipeline(client)
        stage = next(s for s in pipeline["stages"] if s["kind"] == "open")

        async with factory() as session:
            rows = []
            for n in range(3):
                contact_id = str(uuid.uuid4())
                deal_id = str(uuid.uuid4())
                wa = _wa()
                contact_ids.append(contact_id)
                await session.execute(
                    text(
                        "INSERT INTO crm_contacts (id, whatsapp_id, name)"
                        " VALUES (:id, :wa, 'Old owner')"
                    ),
                    {"id": contact_id, "wa": wa},
                )
                # The third contact has no deal at all.
                if n < 2:
                    await session.execute(
                        text(
                            "INSERT INTO crm_deals"
                            " (id, contact_id, pipeline_id, stage_id, title, status, position)"
                            " VALUES (:id, :c, :p, :s, 'Old owner deal', 'open', 0)"
                        ),
                        {
                            "id": deal_id,
                            "c": contact_id,
                            "p": pipeline["id"],
                            "s": stage["id"],
                        },
                    )
                rows.append((contact_id, deal_id, wa))
            await session.commit()

            # 1: no owners anywhere except the dialog -> deal borrows it.
            await session.execute(
                text(
                    "INSERT INTO crm_conversation_state (whatsapp_id, assigned_to)"
                    " VALUES (:wa, :owner)"
                ),
                {"wa": rows[0][2], "owner": first["user"]["id"]},
            )
            # 2: deal owns second, contact and dialog still point at first.
            await session.execute(
                text("UPDATE crm_deals SET owner_id = :owner WHERE id = :id"),
                {"id": rows[1][1], "owner": second["user"]["id"]},
            )
            await session.execute(
                text("UPDATE crm_contacts SET owner_id = :owner WHERE id = :id"),
                {"id": rows[1][0], "owner": first["user"]["id"]},
            )
            await session.execute(
                text(
                    "INSERT INTO crm_conversation_state (whatsapp_id, assigned_to)"
                    " VALUES (:wa, :owner)"
                ),
                {"wa": rows[1][2], "owner": first["user"]["id"]},
            )
            # 3: contact owner without a deal stays untouched.
            await session.execute(
                text("UPDATE crm_contacts SET owner_id = :owner WHERE id = :id"),
                {"id": rows[2][0], "owner": second["user"]["id"]},
            )
            await session.commit()

        async with factory() as session:
            for statement in MIGRATION_SQL:
                await session.execute(text(statement))
            await session.commit()

        first_owners = await _owners(factory, rows[0][0], rows[0][2])
        assert first_owners["deal"] == first["user"]["id"]
        assert first_owners["contact"] == first["user"]["id"]
        assert first_owners["state"] == first["user"]["id"]

        second_owners = await _owners(factory, rows[1][0], rows[1][2])
        assert second_owners["deal"] == second["user"]["id"]
        assert second_owners["contact"] == second["user"]["id"]
        assert second_owners["state"] == second["user"]["id"]

        third_owners = await _owners(factory, rows[2][0], rows[2][2])
        assert third_owners["deal"] is None
        assert third_owners["contact"] == second["user"]["id"]
        assert third_owners["state_exists"] is False
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


def test_migration_downgrade_is_noop():
    path = REPO_ROOT / "backend" / "alembic" / "versions" / "0021_sync_owner.py"
    spec = importlib.util.spec_from_file_location("migration_0021", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0021_sync_owner"
    assert module.down_revision == "0020_board_new_on_top"
    # Old owners were not saved anywhere; re-running the old assignment would
    # only overwrite managers' manual changes made after the upgrade.
    assert module.downgrade() is None
