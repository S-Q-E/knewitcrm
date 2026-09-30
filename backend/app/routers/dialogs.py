from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_user
from ..deps import get_session, pagination
from ..errors import ApiError
from ..models import CrmContact, CrmConversationState, CrmUser
from ..services.activity import log_activity

router = APIRouter(prefix="/api/dialogs", tags=["dialogs"])


class DialogUpdate(BaseModel):
    assigned_to: uuid.UUID | None = None
    bot_paused: bool | None = None


@router.get("")
async def list_dialogs(
    assigned: str | None = Query(default=None, pattern="^(mine|unassigned|all)$"),
    unread: bool = False,
    search: str | None = Query(default=None, max_length=255),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination),
):
    """Conversation list with last message, unread counts, and assignment."""
    stmt = (
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
    if assigned == "mine":
        stmt = stmt.where(CrmConversationState.assigned_to == user.id)
    elif assigned == "unassigned":
        stmt = stmt.where(CrmConversationState.assigned_to.is_(None))
    if unread:
        stmt = stmt.where(CrmConversationState.unread_count > 0)
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                CrmContact.name.ilike(term),
                CrmContact.phone.ilike(term),
                CrmConversationState.whatsapp_id.ilike(term),
            )
        )
    rows = (await session.execute(stmt)).all()
    whatsapp_ids = [row[0].whatsapp_id for row in rows]
    last_messages: dict[str, dict] = {}
    if whatsapp_ids:
        msgs = (
            await session.execute(
                text(
                    "SELECT DISTINCT ON (whatsapp_id) whatsapp_id, direction, content,"
                    " created_at FROM knewit_messages WHERE whatsapp_id = ANY(:ids)"
                    " ORDER BY whatsapp_id, created_at DESC, id DESC"
                ),
                {"ids": whatsapp_ids},
            )
        ).mappings()
        last_messages = {row["whatsapp_id"]: dict(row) for row in msgs}

    items = []
    for state, contact_id, contact_name, contact_phone, assignee_name in rows:
        last = last_messages.get(state.whatsapp_id)
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
                "last_message": {
                    "direction": last["direction"],
                    "content": last["content"],
                    "created_at": last["created_at"].isoformat(),
                }
                if last
                else None,
            }
        )
    items.sort(key=lambda item: (item["last_message"] or {}).get("created_at") or "", reverse=True)
    total = len(items)
    return {"items": items[page["offset"] : page["offset"] + page["limit"]], "total": total}


@router.get("/{whatsapp_id:path}")
async def get_dialog(
    whatsapp_id: str,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    del user
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
    del user
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
