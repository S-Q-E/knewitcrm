from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_user
from ..deps import get_session, pagination
from ..errors import ApiError
from ..models import CrmContact, CrmConversationState, CrmDeal, CrmUser
from ..services.activity import log_activity
from ..services.unanswered import cutoff as unanswered_cutoff
from ..services.unanswered import is_unanswered, unanswered_clause
from ..services.visibility import (
    ensure_lead_visible,
    restrict_managers_to_own,
)

router = APIRouter(prefix="/api/dialogs", tags=["dialogs"])


class DialogUpdate(BaseModel):
    assigned_to: uuid.UUID | None = None
    bot_paused: bool | None = None


@router.get("")
async def list_dialogs(
    assigned: str | None = Query(default=None, pattern="^(mine|unassigned|all)$"),
    unread: bool = False,
    needs_reply: bool = False,
    search: str | None = Query(default=None, max_length=255),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination),
):
    """Conversation list with last message, unread counts, and assignment.

    Pagination and ordering live in SQL: rows come pre-sorted by the cached
    ``last_message_at`` (maintained by the sync and outbox workers), and the
    total comes from a separate COUNT query. Under scoped access managers see
    only their own and unassigned dialogs (responsible = managed deal owner,
    contact owner as fallback).
    """
    managed = (
        select(
            CrmDeal.contact_id.label("contact_id"),
            CrmDeal.id.label("deal_id"),
            CrmDeal.owner_id.label("deal_owner_id"),
        )
        .where(CrmDeal.deleted_at.is_(None))
        .distinct(CrmDeal.contact_id)
        .order_by(CrmDeal.contact_id, CrmDeal.updated_at.desc(), CrmDeal.id)
        .subquery("md")
    )
    base = (
        select(
            CrmConversationState,
            CrmContact.id.label("contact_id"),
            CrmContact.name.label("contact_name"),
            CrmContact.phone.label("contact_phone"),
            CrmUser.name.label("assignee_name"),
        )
        .outerjoin(CrmContact, CrmContact.whatsapp_id == CrmConversationState.whatsapp_id)
        .outerjoin(CrmUser, CrmUser.id == CrmConversationState.assigned_to)
    )
    restricted = await restrict_managers_to_own(session)
    if not user.is_admin and restricted:
        # One aggregate lookup per contact beats a lateral subquery per row;
        # skipped entirely for admins/open access (nothing to filter by).
        base = base.outerjoin(managed, managed.c.contact_id == CrmContact.id)
        effective = case(
            (managed.c.deal_id.is_not(None), managed.c.deal_owner_id),
            else_=CrmContact.owner_id,
        )
        base = base.where(or_(effective.is_(None), effective == user.id))
    if assigned == "mine":
        base = base.where(CrmConversationState.assigned_to == user.id)
    elif assigned == "unassigned":
        base = base.where(CrmConversationState.assigned_to.is_(None))
    if unread:
        base = base.where(CrmConversationState.unread_count > 0)
    cut = await unanswered_cutoff(session)
    if needs_reply:
        base = base.where(unanswered_clause(cut))
    if search:
        term = f"%{search.strip()}%"
        base = base.where(
            or_(
                CrmContact.name.ilike(term),
                CrmContact.phone.ilike(term),
                CrmConversationState.whatsapp_id.ilike(term),
            )
        )
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (
        await session.execute(
            base.order_by(
                CrmConversationState.last_message_at.desc().nulls_last(),
                CrmConversationState.whatsapp_id,
            )
            .limit(page["limit"])
            .offset(page["offset"])
        )
    ).all()

    items = []
    for state, contact_id, contact_name, contact_phone, assignee_name in rows:
        if state.last_message_at is not None:
            last_message: dict[str, str | None] | None = {
                "direction": state.last_message_direction,
                "content": state.last_message_preview,
                "created_at": state.last_message_at.isoformat(),
            }
        else:
            last_message = None
        items.append(
            {
                "whatsapp_id": state.whatsapp_id,
                "contact_id": str(contact_id) if contact_id else None,
                "contact_name": contact_name,
                "contact_phone": contact_phone,
                "bot_paused": state.bot_paused,
                "assigned_to": str(state.assigned_to) if state.assigned_to else None,
                "assignee_name": assignee_name,
                "unread_count": state.unread_count,
                "last_read_at": state.last_read_at.isoformat() if state.last_read_at else None,
                "last_message": last_message,
                "needs_reply": is_unanswered(state, cut),
            }
        )
    return {"items": items, "total": total}


@router.get("/{whatsapp_id:path}/messages")
async def get_dialog_messages(
    whatsapp_id: str,
    limit: int = Query(500, ge=1, le=2000),
    before_id: int | None = Query(default=None, ge=1),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Newest ``limit`` bot messages, oldest first. ``before_id`` pages further back.

    ``has_more`` is true when older messages exist; pass the id of the first item
    of the current page as ``before_id`` to get the page before it.
    """
    lead_exists = (
        await session.execute(
            text("SELECT 1 FROM knewit_leads WHERE whatsapp_id = :wa"), {"wa": whatsapp_id}
        )
    ).scalar_one_or_none()
    if lead_exists is None:
        raise ApiError("LEAD_NOT_FOUND", "Dialog not found", 404)
    await ensure_lead_visible(session, whatsapp_id, user)
    params: dict[str, object] = {"whatsapp_id": whatsapp_id, "limit": limit + 1}
    cursor = ""
    if before_id is not None:
        cursor = (
            " AND (created_at, id) < (SELECT created_at, id FROM knewit_messages"
            " WHERE id = :before_id AND whatsapp_id = :whatsapp_id)"
        )
        params["before_id"] = before_id
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id, direction, message_type, content, stage_at_moment,"
                    " created_at FROM knewit_messages"
                    " WHERE whatsapp_id = :whatsapp_id" + cursor + " ORDER BY created_at DESC,"
                    " id DESC LIMIT :limit"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    has_more = len(rows) > limit
    return {
        "items": [
            {
                "id": row["id"],
                "direction": row["direction"],
                "message_type": row["message_type"],
                "content": row["content"],
                "stage_at_moment": row["stage_at_moment"],
                "created_at": row["created_at"].isoformat(),
            }
            for row in reversed(rows[:limit])
        ],
        "has_more": has_more,
    }


@router.get("/{whatsapp_id:path}")
async def get_dialog(
    whatsapp_id: str,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    await ensure_lead_visible(session, whatsapp_id, user)
    state = await session.get(CrmConversationState, whatsapp_id)
    contact = (
        await session.execute(select(CrmContact).where(CrmContact.whatsapp_id == whatsapp_id))
    ).scalar_one_or_none()
    if state is None and contact is None:
        raise ApiError("NOT_FOUND", "Dialog not found", 404)
    assignee_name = None
    if state and state.assigned_to:
        owner = await session.get(CrmUser, state.assigned_to)
        assignee_name = owner.name if owner else None
    return {
        "whatsapp_id": whatsapp_id,
        "contact_id": str(contact.id) if contact else None,
        "contact_name": contact.name if contact else None,
        "contact_phone": contact.phone if contact else None,
        "bot_paused": state.bot_paused if state else False,
        "assigned_to": str(state.assigned_to) if state and state.assigned_to else None,
        "assignee_name": assignee_name,
        "unread_count": state.unread_count if state else 0,
        "last_read_at": state.last_read_at.isoformat() if state and state.last_read_at else None,
    }


@router.post("/{whatsapp_id:path}/read")
async def mark_dialog_read(
    whatsapp_id: str,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    await ensure_lead_visible(session, whatsapp_id, user)
    state = await session.get(CrmConversationState, whatsapp_id)
    if state is None:
        state = CrmConversationState(whatsapp_id=whatsapp_id)
        session.add(state)
    state.unread_count = 0
    state.last_read_at = datetime.now(UTC)
    await session.commit()
    return {"ok": True, "whatsapp_id": whatsapp_id}


@router.patch("/{whatsapp_id:path}")
async def update_dialog(
    whatsapp_id: str,
    payload: DialogUpdate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    await ensure_lead_visible(session, whatsapp_id, user)
    state = await session.get(CrmConversationState, whatsapp_id)
    if state is None:
        state = CrmConversationState(whatsapp_id=whatsapp_id)
        session.add(state)
    if "assigned_to" in payload.model_fields_set:
        if payload.assigned_to is not None:
            assignee = await session.get(CrmUser, payload.assigned_to)
            if assignee is None:
                raise ApiError("UNKNOWN_USER", "User not found", 422)
        state.assigned_to = payload.assigned_to
    if payload.bot_paused is not None:
        state.bot_paused = payload.bot_paused
        state.paused_by = user.id if payload.bot_paused else None
        state.paused_at = datetime.now(UTC) if payload.bot_paused else None
    await session.commit()
    await log_activity(
        session, user.id, "dialog", None, "dialog_updated", {"whatsapp_id": whatsapp_id}
    )
    await session.commit()
    return await get_dialog(whatsapp_id, user, session)
