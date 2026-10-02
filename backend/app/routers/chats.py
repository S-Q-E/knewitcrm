from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_role, require_user
from ..deps import get_session, pagination
from ..errors import ApiError, error_payload
from ..models import CrmContact, CrmConversationState, CrmOutbox, CrmQuickReply, CrmUser
from ..schemas.chats import ChatMessageIn, OutboxOut, QuickReplyOut
from ..schemas.settings import QuickReplyCreate, QuickReplyUpdate
from ..services.activity import diff_payload, log_activity, slim
from ..services.event_bus import bus
from ..services.ratelimit import send_limiter
from ..services.visibility import (
    ensure_visible,
    is_visible,
    lead_owner,
    restrict_managers_to_own,
)

router = APIRouter(prefix="/api/chats", tags=["chats"])

require_admin = require_role("admin")

SETTING_AUTOPAUSE_ON_MANUAL_REPLY = "auto_pause_on_manual_reply"


async def _autopause_enabled(session: AsyncSession) -> bool:
    """Manager send auto-pauses the bot unless explicitly disabled (default true)."""
    value = (
        await session.execute(
            text("SELECT value FROM crm_settings WHERE key = :key"),
            {"key": SETTING_AUTOPAUSE_ON_MANUAL_REPLY},
        )
    ).scalar_one_or_none()
    return value is not False


async def _ensure_state(session: AsyncSession, whatsapp_id: str) -> CrmConversationState:
    state = await session.get(CrmConversationState, whatsapp_id)
    if state is None:
        state = CrmConversationState(whatsapp_id=whatsapp_id)
        session.add(state)
        await session.flush()
    return state


async def _contact_id(session: AsyncSession, whatsapp_id: str) -> uuid.UUID | None:
    return (
        await session.execute(select(CrmContact.id).where(CrmContact.whatsapp_id == whatsapp_id))
    ).scalar_one_or_none()


async def _lead_exists(session: AsyncSession, whatsapp_id: str) -> bool:
    return (
        await session.execute(
            text("SELECT 1 FROM knewit_leads WHERE whatsapp_id = :wa"), {"wa": whatsapp_id}
        )
    ).scalar_one_or_none() is not None


async def _ensure_lead_visible(session: AsyncSession, whatsapp_id: str, user: CurrentUser) -> None:
    """404 when the bot lead is gone; hides foreign leads under scoped access."""
    if not await _lead_exists(session, whatsapp_id):
        raise ApiError("LEAD_NOT_FOUND", "Dialog not found", 404)
    restricted = await restrict_managers_to_own(session)
    ensure_visible(is_visible(await lead_owner(session, whatsapp_id), user, restricted))


async def _log_pause_event(
    session: AsyncSession,
    user: CurrentUser,
    whatsapp_id: str,
    action: str,
    paused: bool,
) -> None:
    """Pause/resume timeline event, contact-scoped so it shows in the deal timeline."""
    contact_id = await _contact_id(session, whatsapp_id)
    await log_activity(
        session,
        user.id,
        "contact" if contact_id is not None else "dialog",
        contact_id,
        action,
        {"whatsapp_id": whatsapp_id, "bot_paused": paused},
    )


def _pause(state: CrmConversationState, user: CurrentUser) -> bool:
    """Pause the bot; returns True on an actual transition (for timeline logging)."""
    if state.bot_paused:
        return False
    state.bot_paused = True
    state.paused_by = user.id
    state.paused_at = datetime.now(UTC)
    return True


def _pause_payload(state: CrmConversationState) -> dict[str, Any]:
    return {
        "whatsapp_id": state.whatsapp_id,
        "bot_paused": state.bot_paused,
        "paused_by": str(state.paused_by) if state.paused_by else None,
        "paused_at": state.paused_at.isoformat() if state.paused_at else None,
    }


@router.get("/quick-replies")
async def list_quick_replies(
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    del user
    rows = (
        await session.execute(
            select(CrmQuickReply).order_by(CrmQuickReply.sort, CrmQuickReply.title)
        )
    ).scalars()
    return {"items": [QuickReplyOut.model_validate(row).model_dump() for row in rows]}


@router.post("/quick-replies", response_model=QuickReplyOut, status_code=201)
async def create_quick_reply(
    payload: QuickReplyCreate,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    row = CrmQuickReply(title=payload.title.strip(), body=payload.body.strip(), sort=payload.sort)
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError("QUICK_REPLY_EXISTS", "A quick reply with this title exists", 409) from exc
    await session.refresh(row)
    await log_activity(
        session,
        admin.id,
        "quick_reply",
        row.id,
        "quick_reply_created",
        diff_payload(None, slim({"title": row.title})),
    )
    await session.commit()
    return row


@router.patch("/quick-replies/{reply_id}", response_model=QuickReplyOut)
async def update_quick_reply(
    reply_id: uuid.UUID,
    payload: QuickReplyUpdate,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(CrmQuickReply, reply_id)
    if row is None:
        raise ApiError("NOT_FOUND", "Quick reply not found", 404)
    before = slim({"title": row.title, "sort": row.sort})
    if payload.title is not None:
        row.title = payload.title.strip()
    if payload.body is not None:
        row.body = payload.body.strip()
    if payload.sort is not None:
        row.sort = payload.sort
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError("QUICK_REPLY_EXISTS", "A quick reply with this title exists", 409) from exc
    await session.refresh(row)
    await log_activity(
        session,
        admin.id,
        "quick_reply",
        row.id,
        "quick_reply_updated",
        diff_payload(before, slim({"title": row.title, "sort": row.sort})),
    )
    await session.commit()
    return row


@router.delete("/quick-replies/{reply_id}")
async def delete_quick_reply(
    reply_id: uuid.UUID,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(CrmQuickReply, reply_id)
    if row is None:
        raise ApiError("NOT_FOUND", "Quick reply not found", 404)
    await log_activity(
        session,
        admin.id,
        "quick_reply",
        row.id,
        "quick_reply_deleted",
        diff_payload(slim({"title": row.title}), None),
    )
    await session.delete(row)
    await session.commit()
    return {"ok": True}


@router.get("/outbox")
async def list_outbox_global(
    status: str | None = Query(default=None, pattern="^(queued|sending|sent|failed)$"),
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination),
):
    """Delivery journal across all dialogs (admin)."""
    del admin
    stmt = select(CrmOutbox, CrmUser.name).outerjoin(CrmUser, CrmUser.id == CrmOutbox.sent_by)
    if status is not None:
        stmt = stmt.where(CrmOutbox.status == status)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await session.execute(
            stmt.order_by(CrmOutbox.created_at.desc(), CrmOutbox.id.desc())
            .limit(page["limit"])
            .offset(page["offset"])
        )
    ).all()
    return {
        "items": [
            {
                **OutboxOut.model_validate(row).model_dump(mode="json"),
                "sent_by_name": name,
            }
            for row, name in rows
        ],
        "total": total,
    }


@router.post("/outbox/{outbox_id}/retry", response_model=OutboxOut)
async def retry_outbox(
    outbox_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(CrmOutbox, outbox_id)
    if row is None:
        raise ApiError("OUTBOX_NOT_FOUND", "Outbox message not found", 404)
    if not user.is_admin and row.sent_by != user.id:
        raise ApiError("FORBIDDEN", "Only the author or an admin can retry", 403)
    if row.status != "failed":
        raise ApiError("NOT_RETRYABLE", "Only failed messages can be retried", 422)
    row.status = "queued"
    row.attempts = 0
    row.error = None
    row.next_attempt_at = None
    row.claimed_at = None
    await session.commit()
    await session.refresh(row)
    bus.publish(
        "outbox_status",
        {"outbox_id": str(row.id), "whatsapp_id": row.whatsapp_id, "status": "queued"},
    )
    return row


@router.post(
    "/{whatsapp_id:path}/messages", response_model=OutboxOut, status_code=status.HTTP_202_ACCEPTED
)
async def queue_message(
    whatsapp_id: str,
    payload: ChatMessageIn,
    request: Request,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    settings = request.app.state.settings
    if not send_limiter.check(
        str(user.id), max_hits=settings.rate_limit_send_per_minute, window=60
    ):
        return JSONResponse(
            status_code=429,
            content=error_payload("RATE_LIMITED", "Too many messages, slow down"),
            headers={"Retry-After": str(send_limiter.retry_after(str(user.id)))},
        )
    body = payload.body.strip()
    if not body:
        raise ApiError("EMPTY_BODY", "Message body must not be empty", 422)
    await _ensure_lead_visible(session, whatsapp_id, user)
    row = CrmOutbox(whatsapp_id=whatsapp_id, body=body, sent_by=user.id, status="queued")
    session.add(row)
    state = await _ensure_state(session, whatsapp_id)
    paused_now = await _autopause_enabled(session) and _pause(state, user)
    if paused_now:
        await _log_pause_event(session, user, whatsapp_id, "bot_paused", True)
    await session.commit()
    await session.refresh(row)
    bus.publish(
        "outbox_status",
        {"outbox_id": str(row.id), "whatsapp_id": whatsapp_id, "status": "queued"},
    )
    if paused_now:
        bus.publish("bot_paused", {"whatsapp_id": whatsapp_id, "paused": True})
    return row


@router.get("/{whatsapp_id:path}/outbox")
async def list_outbox(
    whatsapp_id: str,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination),
):
    await _ensure_lead_visible(session, whatsapp_id, user)
    total = (
        await session.execute(
            select(func.count()).select_from(CrmOutbox).where(CrmOutbox.whatsapp_id == whatsapp_id)
        )
    ).scalar() or 0
    rows = (
        await session.execute(
            select(CrmOutbox)
            .where(CrmOutbox.whatsapp_id == whatsapp_id)
            .order_by(CrmOutbox.created_at.desc(), CrmOutbox.id.desc())
            .limit(page["limit"])
            .offset(page["offset"])
        )
    ).scalars()
    return {
        "items": [OutboxOut.model_validate(row).model_dump(mode="json") for row in rows],
        "total": total,
    }


@router.post("/{whatsapp_id:path}/bot/pause")
async def pause_bot(
    whatsapp_id: str,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    await _ensure_lead_visible(session, whatsapp_id, user)
    state = await _ensure_state(session, whatsapp_id)
    if _pause(state, user):
        await _log_pause_event(session, user, whatsapp_id, "bot_paused", True)
    await session.commit()
    await session.refresh(state)
    bus.publish("bot_paused", {"whatsapp_id": whatsapp_id, "paused": True})
    return _pause_payload(state)


@router.post("/{whatsapp_id:path}/bot/resume")
async def resume_bot(
    whatsapp_id: str,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    await _ensure_lead_visible(session, whatsapp_id, user)
    state = await _ensure_state(session, whatsapp_id)
    if state.bot_paused:
        state.bot_paused = False
        state.paused_by = None
        state.paused_at = None
        await _log_pause_event(session, user, whatsapp_id, "bot_resumed", False)
    await session.commit()
    await session.refresh(state)
    bus.publish("bot_paused", {"whatsapp_id": whatsapp_id, "paused": False})
    return _pause_payload(state)
