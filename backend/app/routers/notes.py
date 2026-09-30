from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_user
from ..deps import get_session, pagination
from ..errors import ApiError
from ..models import CrmNote
from ..schemas.meta import (
    NoteCreate,
    NoteListOut,
    NoteOut,
    NoteUpdate,
)
from ..services.activity import diff_payload, log_activity, slim

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.get("", response_model=NoteListOut)
async def list_notes(
    deal_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    pinned: bool | None = None,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination),
):
    del user
    stmt = select(CrmNote)
    if deal_id is not None:
        stmt = stmt.where(CrmNote.deal_id == deal_id)
    if contact_id is not None:
        stmt = stmt.where(CrmNote.contact_id == contact_id)
    if pinned is not None:
        stmt = stmt.where(CrmNote.pinned.is_(pinned))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await session.execute(
            stmt.order_by(CrmNote.pinned.desc(), CrmNote.created_at.desc())
            .limit(page["limit"])
            .offset(page["offset"])
        )
    ).scalars()
    return NoteListOut(items=[NoteOut.model_validate(n) for n in rows], total=total)


@router.post("", response_model=NoteOut, status_code=201)
async def create_note(
    payload: NoteCreate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    if payload.deal_id is None and payload.contact_id is None:
        raise ApiError("NOTE_TARGET_REQUIRED", "deal_id or contact_id is required", 422)
    if payload.deal_id is not None:
        from ..models import CrmDeal

        deal = await session.get(CrmDeal, payload.deal_id)
        if deal is None or deal.deleted_at is not None:
            raise ApiError("UNKNOWN_DEAL", "Deal not found", 422)
    if payload.contact_id is not None:
        from ..models import CrmContact

        contact = await session.get(CrmContact, payload.contact_id)
        if contact is None or contact.deleted_at is not None:
            raise ApiError("UNKNOWN_CONTACT", "Contact not found", 422)
    note = CrmNote(
        deal_id=payload.deal_id,
        contact_id=payload.contact_id,
        author_id=user.id,
        body=payload.body.strip(),
        pinned=payload.pinned,
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)
    await log_activity(
        session,
        user.id,
        "note",
        note.id,
        "note_created",
        diff_payload(None, slim({"body": note.body[:200]})),
    )
    await session.commit()
    return NoteOut.model_validate(note)


@router.get("/{note_id}", response_model=NoteOut)
async def get_note(
    note_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    del user
    note = await session.get(CrmNote, note_id)
    if note is None:
        raise ApiError("NOT_FOUND", "Note not found", 404)
    return NoteOut.model_validate(note)


@router.patch("/{note_id}", response_model=NoteOut)
async def update_note(
    note_id: uuid.UUID,
    payload: NoteUpdate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    note = await session.get(CrmNote, note_id)
    if note is None:
        raise ApiError("NOT_FOUND", "Note not found", 404)
    before = slim({"body": note.body[:200], "pinned": note.pinned})
    if payload.body is not None:
        note.body = payload.body.strip()
    if payload.pinned is not None:
        note.pinned = payload.pinned
    await session.commit()
    await session.refresh(note)
    await log_activity(
        session,
        user.id,
        "note",
        note.id,
        "note_updated",
        diff_payload(before, slim({"body": note.body[:200], "pinned": note.pinned})),
    )
    await session.commit()
    return NoteOut.model_validate(note)


@router.delete("/{note_id}")
async def delete_note(
    note_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    note = await session.get(CrmNote, note_id)
    if note is None:
        raise ApiError("NOT_FOUND", "Note not found", 404)
    if not user.is_admin and note.author_id != user.id:
        raise ApiError("FORBIDDEN", "Only the author or an admin can delete a note", 403)
    await log_activity(
        session,
        user.id,
        "note",
        note.id,
        "note_deleted",
        diff_payload(slim({"body": note.body[:200]}), None),
    )
    await session.delete(note)
    await session.commit()
    return {"ok": True}
