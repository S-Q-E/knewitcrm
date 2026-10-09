from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_user
from ..security import SESSION_COOKIE
from ..services.event_bus import bus
from ..services.visibility import is_visible, lead_owner, restrict_managers_to_own
from ..session_middleware import session_still_active

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stream", tags=["stream"])

# SSE comment heartbeat; keeps proxies from closing idle connections.
HEARTBEAT_SECONDS = 15
# A revoked, expired or deactivated session must not keep receiving events for long.
SESSION_RECHECK_SECONDS = 60


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
    if kind == "task_created":
        if user.is_admin or not restricted:
            return True
        assignee_id = data.get("assignee_id")
        return assignee_id is None or str(assignee_id) == str(user.id)
    return True


async def whatsapp_visible(
    session: AsyncSession,
    cache: dict[str, bool],
    whatsapp_id: str | None,
    user: CurrentUser,
    restricted: bool,
) -> bool:
    """Visibility of bot-table events by the responsible deal owner.

    Leads without a live deal or contact count as unassigned (visible).
    Results are cached per connection; a scope change applies on reconnect.
    """
    if user.is_admin or not restricted or not whatsapp_id:
        return True
    if whatsapp_id in cache:
        return cache[whatsapp_id]
    visible = is_visible(await lead_owner(session, whatsapp_id), user, restricted)
    cache[whatsapp_id] = visible
    return visible


def format_sse(type: str, data: dict[str, Any]) -> str:
    return f"event: {type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("")
async def stream(
    request: Request,
    user: CurrentUser = Depends(require_user),
):
    factory = request.app.state.session_factory
    token_value = request.cookies.get(SESSION_COOKIE, "")
    # Visibility snapshot per connection; a role/scope change applies on reconnect.
    # Short-lived session: the stream itself must not hold a pool connection.
    async with factory() as session:
        restricted = await restrict_managers_to_own(session)

    async def generate():
        queue = bus.subscribe()
        owner_cache: dict[str, bool] = {}
        loop = asyncio.get_running_loop()
        checked_at = loop.time()
        try:
            yield ": connected\n\n"
            while True:
                if loop.time() - checked_at >= SESSION_RECHECK_SECONDS:
                    checked_at = loop.time()
                    owner_cache.clear()
                    if not await session_still_active(factory, token_value):
                        logger.info("stream closed: session is no longer active")
                        break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if await request.is_disconnected():
                    break
                if not event_visible(event, user, restricted):
                    continue
                if event["type"] in ("new_message", "bot_event", "outbox_status", "bot_paused"):
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
