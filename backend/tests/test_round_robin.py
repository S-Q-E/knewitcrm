from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text

from backend.tests.conftest import csrf_headers
from backend.tests.crm_helpers import (
    admin_csrf,
    create_contact,
    default_pipeline,
    engine_factory,
    make_manager,
    purge_contacts,
    purge_rows,
)

pytestmark = pytest.mark.usefixtures("db_available")


def _wa() -> str:
    return f"7999{uuid.uuid4().hex[:8]}@c.us"


async def _set_round_robin(factory, enabled: bool) -> None:
    async with factory() as session:
        if enabled:
            await session.execute(
                text(
                    "INSERT INTO crm_settings (key, value) VALUES"
                    ' (\'deal_assignment\', \'{"mode": "round_robin", "last_index": -1}\')'
                    " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
                )
            )
        else:
            await session.execute(text("DELETE FROM crm_settings WHERE key = 'deal_assignment'"))
        await session.commit()


async def test_parallel_deal_creation_distributes_evenly(client, settings):
    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    deal_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        first = await make_manager(client, token)
        second = await make_manager(client, token)
        contact = await create_contact(client, token, whatsapp_id=_wa())
        contact_ids.append(contact["id"])
        pipeline = await default_pipeline(client)
        stage_id = next(s["id"] for s in pipeline["stages"] if s["kind"] == "open")

        async def _create_one(n: int) -> str:
            response = await client.post(
                "/api/deals",
                json={
                    "contact_id": contact["id"],
                    "pipeline_id": pipeline["id"],
                    "stage_id": stage_id,
                    "title": f"RR deal {n} {uuid.uuid4().hex[:6]}",
                },
                headers=csrf_headers(token),
            )
            assert response.status_code == 201, response.text
            return response.json()["owner_id"]

        await _set_round_robin(factory, True)
        try:
            # Isolate the roster: leftover managers from other tests would
            # skew the distribution, so park them (reactivated in finally).
            async with factory() as session:
                await session.execute(
                    text(
                        "UPDATE crm_users SET is_active = false"
                        " WHERE role = 'manager' AND is_active"
                        f" AND id NOT IN ('{first['user']['id']}', '{second['user']['id']}')"
                    )
                )
                await session.commit()
            try:
                owners = await asyncio.gather(*[_create_one(n) for n in range(10)])
            finally:
                async with factory() as session:
                    await session.execute(
                        text("UPDATE crm_users SET is_active = true WHERE role = 'manager'")
                    )
                    await session.commit()
        finally:
            await _set_round_robin(factory, False)

        from collections import Counter

        counts = Counter(owners)
        assert set(counts) == {first["user"]["id"], second["user"]["id"]}
        assert set(counts.values()) == {5}, f"uneven: {counts}"

        async with factory() as session:
            deal_ids = (
                (
                    await session.execute(
                        text("SELECT id FROM crm_deals WHERE contact_id = :id"),
                        {"id": contact["id"]},
                    )
                )
                .scalars()
                .all()
            )
            deal_ids = [str(d) for d in deal_ids]
    finally:
        await purge_rows(factory, "crm_deals", deal_ids)
        await purge_contacts(factory, contact_ids)
        await engine.dispose()
