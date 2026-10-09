from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from backend.tests.conftest import csrf_headers
from backend.tests.crm_helpers import admin_csrf, create_contact, engine_factory, purge_contacts

pytestmark = pytest.mark.usefixtures("db_available")


def _wa() -> str:
    return f"7999{uuid.uuid4().hex[:8]}@c.us"


async def _wa_of(factory, contact_id: str) -> str | None:
    async with factory() as session:
        return (
            await session.execute(
                text("SELECT whatsapp_id FROM crm_contacts WHERE id = :id"), {"id": contact_id}
            )
        ).scalar_one()


async def test_merge_moves_whatsapp_id_from_bot_contact_to_manual_winner(client, settings):
    engine, factory = engine_factory(settings)
    ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        winner = await create_contact(client, token, name="Manual winner")
        ids.append(winner["id"])
        bot_wa = _wa()
        loser = await create_contact(client, token, name="Bot loser", whatsapp_id=bot_wa)
        ids.append(loser["id"])

        merged = await client.post(
            "/api/contacts/merge",
            json={"winner_id": winner["id"], "loser_id": loser["id"]},
            headers=csrf_headers(token),
        )
        assert merged.status_code == 200, merged.text
        assert await _wa_of(factory, winner["id"]) == bot_wa
        assert await _wa_of(factory, loser["id"]) is None
    finally:
        await purge_contacts(factory, ids)
        await engine.dispose()


async def test_merge_with_two_different_whatsapp_ids_is_refused_without_changes(client, settings):
    engine, factory = engine_factory(settings)
    ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        winner_wa, loser_wa = _wa(), _wa()
        winner = await create_contact(client, token, name="Winner", whatsapp_id=winner_wa)
        ids.append(winner["id"])
        loser = await create_contact(client, token, name="Loser", whatsapp_id=loser_wa)
        ids.append(loser["id"])

        refused = await client.post(
            "/api/contacts/merge",
            json={"winner_id": winner["id"], "loser_id": loser["id"]},
            headers=csrf_headers(token),
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["code"] == "MERGE_WHATSAPP_CONFLICT"
        assert await _wa_of(factory, winner["id"]) == winner_wa
        assert await _wa_of(factory, loser["id"]) == loser_wa
    finally:
        await purge_contacts(factory, ids)
        await engine.dispose()
