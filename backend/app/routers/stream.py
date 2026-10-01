from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_user
from ..deps import get_session
from ..models import CrmContact
from ..services.event_bus import bus
from ..services.visibility import is_visible, restrict_managers_to_own

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stream", tags=["stream"])

# SSE comment heartbeat; keeps proxies from closing idle connections.
HEARTBEAT_SECONDS = 15


def event_visible(event: dict[str, Any], user: CurrentUser, restricted: bool) -> bool:
    """Per-user filter mirror of the REST visibility rules."""
    kind = event.get("type")
    data = event.get("data") or {}
    if kind == "notification":
        return str(data.get("user_id")) == str(user.id)
    if kind in ("deal_moved", "deal_updated"):
        if user.is_admin or not restricted:
            return True
        owner_id = data.get("owner_id")
        return owner_id is None or str(owner_id) == str(user.id)
    return True


async def whatsapp_visible(
    session: AsyncSession,
    cache: dict[str, bool],
    whatsapp_id: str | None,
    user: CurrentUser,
    restricted: bool,
) -> bool:
    """Visibility of bot-table events by the linked contact owner.

    Leads without a CRM contact yet count as unassigned (visible to all).
    Results are cached per connection; a scope change applies on reconnect.
    """
    if user.is_admin or not restricted or not whatsapp_id:
        return True
    if whatsapp_id in cache:
        return cache[whatsapp_id]
    owner_id = (
        await session.execute(
            select(CrmContact.owner_id).where(CrmContact.whatsapp_id == whatsapp_id)
        )
    ).scalar_one_or_none()
    visible = is_visible(owner_id, user, restricted)
    cache[whatsapp_id] = visible
    return visible


def format_sse(type: str, data: dict[str, Any]) -> str:
    return f"event: {type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("")
async def stream(
    request: Request,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    # Visibility snapshot per connection; a role/scope change applies on reconnect.
    restricted = await restrict_managers_to_own(session)
    factory = request.app.state.session_factory

    async def generate():
        queue = bus.subscribe()
        owner_cache: dict[str, bool] = {}
        try:
            yield ": connected\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if await request.is_disconnected():
                    break
                if not event_visible(event, user, restricted):
                    continue
                if event["type"] in ("new_message", "bot_event"):
                    async with factory() as lookup:
                        if not await whatsapp_visible(
                            lookup,
                            owner_cache,
                            (event.get("data") or {}).get("whatsapp_id"),
                            user,
                            restricted,
                        ):
                            continue
                yield format_sse(event["type"], event["data"])
        except asyncio.CancelledError:
            raise
        finally:
            bus.unsubscribe(queue)
            logger.debug("stream closed user=%s", user.email)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
