from __future__ import annotations

import uuid

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.tests.conftest import csrf_headers, login, login_admin, unique_email

MANAGER_PASSWORD = "manager-password-1"


def engine_factory(settings):
    engine = create_async_engine(settings.sqlalchemy_url, connect_args=settings.connect_args)
    return engine, async_sessionmaker(bind=engine, expire_on_commit=False)


async def run_sync(factory):
    """Run one bot-sync cycle against a session factory (commits)."""
    from backend.app.workers.sync_worker import run_sync_cycle

    return await run_sync_cycle(factory)


async def admin_csrf(client, settings) -> str:
    return (await login_admin(client, settings))["csrf"]


async def make_manager(client, admin_token: str) -> dict:
    email = unique_email("manager")
    response = await client.post(
        "/api/users",
        json={
            "email": email,
            "name": "Case Manager",
            "password": MANAGER_PASSWORD,
            "role": "manager",
        },
        headers=csrf_headers(admin_token),
    )
    assert response.status_code == 201, response.text
    return {"email": email, "password": MANAGER_PASSWORD, "user": response.json()}


class ManagerSession:
    """A second logged-in client (separate cookie jar) for permission tests."""

    def __init__(self, app, email: str, password: str):
        self._app = app
        self._email = email
        self._password = password
        self.client: AsyncClient | None = None
        self.csrf = ""

    async def __aenter__(self):
        self._lifespan = LifespanManager(self._app)
        await self._lifespan.__aenter__()
        self.client = AsyncClient(transport=ASGITransport(app=self._app), base_url="http://test")
        await self.client.__aenter__()
        self.csrf = (await login(self.client, self._email, self._password))["csrf"]
        return self

    async def __aexit__(self, *exc):
        await self.client.__aexit__(*exc)
        await self._lifespan.__aexit__(*exc)

    def headers(self) -> dict:
        return csrf_headers(self.csrf)


async def default_pipeline(client) -> dict:
    response = await client.get("/api/pipelines")
    assert response.status_code == 200
    pipelines = response.json()
    assert pipelines, "default funnel must be seeded"
    for pipeline in pipelines:
        if pipeline.get("is_default"):
            return pipeline
    return pipelines[0]


def open_stage(pipeline: dict) -> dict:
    for stage in pipeline["stages"]:
        if stage["kind"] == "open":
            return stage
    raise AssertionError("no open stage")


async def create_contact(client, token: str, **overrides) -> dict:
    payload = {"name": f"Test {uuid.uuid4().hex[:8]}", **overrides}
    response = await client.post("/api/contacts", json=payload, headers=csrf_headers(token))
    assert response.status_code == 201, response.text
    return response.json()


async def create_deal(client, token: str, contact_id: str, pipeline: dict, **overrides) -> dict:
    payload = {
        "contact_id": contact_id,
        "pipeline_id": pipeline["id"],
        "stage_id": open_stage(pipeline)["id"],
        "title": f"Deal {uuid.uuid4().hex[:8]}",
        **overrides,
    }
    response = await client.post("/api/deals", json=payload, headers=csrf_headers(token))
    assert response.status_code == 201, response.text
    return response.json()


async def assert_logged(factory, entity: str, entity_id: str, action: str) -> None:
    async with factory() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT diff FROM crm_activity_log"
                        " WHERE entity = :entity AND entity_id = :id AND action = :action"
                        " ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"entity": entity, "id": entity_id, "action": action},
                )
            )
            .mappings()
            .one_or_none()
        )
    assert row is not None, f"missing activity log {entity}/{action}"


async def purge_contacts(factory, contact_ids: list[str]) -> None:
    if not contact_ids:
        return
    async with factory() as session:
        deals = (
            (
                await session.execute(
                    text("SELECT id FROM crm_deals WHERE contact_id = ANY(:ids)"),
                    {"ids": contact_ids},
                )
            )
            .scalars()
            .all()
        )
        for deal_id in deals:
            await session.execute(
                text("DELETE FROM crm_deal_stage_history WHERE deal_id = :id"), {"id": deal_id}
            )
            await session.execute(
                text("DELETE FROM crm_activity_log WHERE entity_id = :id"), {"id": deal_id}
            )
            await session.execute(
                text("DELETE FROM crm_entity_tags WHERE entity = 'deal' AND entity_id = :id"),
                {"id": deal_id},
            )
            await session.execute(
                text("DELETE FROM crm_notes WHERE deal_id = :id"), {"id": deal_id}
            )
        await session.execute(
            text("DELETE FROM crm_deals WHERE contact_id = ANY(:ids)"), {"ids": contact_ids}
        )
        for contact_id in contact_ids:
            await session.execute(
                text("DELETE FROM crm_activity_log WHERE entity_id = :id"), {"id": contact_id}
            )
            await session.execute(
                text("DELETE FROM crm_entity_tags WHERE entity = 'contact' AND entity_id = :id"),
                {"id": contact_id},
            )
            await session.execute(
                text("DELETE FROM crm_notes WHERE contact_id = :id"), {"id": contact_id}
            )
        whatsapps = (
            (
                await session.execute(
                    text("SELECT whatsapp_id FROM crm_contacts WHERE id = ANY(:ids)"),
                    {"ids": contact_ids},
                )
            )
            .scalars()
            .all()
        )
        await session.execute(
            text("DELETE FROM crm_contacts WHERE id = ANY(:ids)"), {"ids": contact_ids}
        )
        for wa in whatsapps:
            if wa:
                await session.execute(
                    text("DELETE FROM crm_conversation_state WHERE whatsapp_id = :wa"), {"wa": wa}
                )
                await session.execute(
                    text("DELETE FROM knewit_messages WHERE whatsapp_id = :wa"), {"wa": wa}
                )
                await session.execute(
                    text("DELETE FROM knewit_events WHERE whatsapp_id = :wa"), {"wa": wa}
                )
                await session.execute(
                    text("DELETE FROM knewit_leads WHERE whatsapp_id = :wa"), {"wa": wa}
                )
        await session.commit()


async def purge_pipelines(factory, pipeline_ids: list[str]) -> None:
    if not pipeline_ids:
        return
    async with factory() as session:
        await session.execute(
            text("DELETE FROM crm_stages WHERE pipeline_id = ANY(:ids)"), {"ids": pipeline_ids}
        )
        await session.execute(
            text("DELETE FROM crm_pipelines WHERE id = ANY(:ids)"), {"ids": pipeline_ids}
        )
        await session.commit()


async def purge_rows(factory, table: str, ids: list[str]) -> None:
    if not ids:
        return
    async with factory() as session:
        await session.execute(text(f"DELETE FROM {table} WHERE id = ANY(:ids)"), {"ids": ids})
        await session.commit()
