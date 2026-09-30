from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_user
from ..deps import get_session, pagination
from ..errors import ApiError
from ..models import CrmSavedView
from ..schemas.views import (
    SavedViewCreate,
    SavedViewListOut,
    SavedViewOut,
    SavedViewUpdate,
)
from ..services.activity import diff_payload, log_activity, slim

router = APIRouter(prefix="/api/saved-views", tags=["saved-views"])


def _can_edit(view: CrmSavedView, user: CurrentUser) -> bool:
    return user.is_admin or (view.user_id is not None and view.user_id == user.id)


@router.get("", response_model=SavedViewListOut)
async def list_saved_views(
    entity: str | None = Query(default=None, pattern="^(deal|contact)$"),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination),
):
    stmt = select(CrmSavedView).where(
        or_(CrmSavedView.user_id == user.id, CrmSavedView.is_shared.is_(True))
    )
    if entity is not None:
        stmt = stmt.where(CrmSavedView.entity == entity)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await session.execute(
            stmt.order_by(CrmSavedView.created_at.desc())
            .limit(page["limit"])
            .offset(page["offset"])
        )
    ).scalars()
    return SavedViewListOut(items=[SavedViewOut.model_validate(v) for v in rows], total=total)


@router.post("", response_model=SavedViewOut, status_code=201)
async def create_saved_view(
    payload: SavedViewCreate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    if payload.is_shared and not user.is_admin:
        raise ApiError("FORBIDDEN", "Only admins can share views", 403)
    view = CrmSavedView(
        user_id=user.id,
        entity=payload.entity,
        name=payload.name.strip(),
        filters=payload.filters,
        is_shared=payload.is_shared,
    )
    session.add(view)
    await session.commit()
    await session.refresh(view)
    await log_activity(
        session,
        user.id,
        "saved_view",
        view.id,
        "saved_view_created",
        diff_payload(None, slim({"name": view.name, "entity": view.entity})),
    )
    await session.commit()
    return SavedViewOut.model_validate(view)


@router.patch("/{view_id}", response_model=SavedViewOut)
async def update_saved_view(
    view_id: uuid.UUID,
    payload: SavedViewUpdate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    view = await session.get(CrmSavedView, view_id)
    if view is None:
        raise ApiError("NOT_FOUND", "Saved view not found", 404)
    if not _can_edit(view, user):
        raise ApiError("FORBIDDEN", "Only the owner or an admin can edit this view", 403)
    before = slim({"name": view.name, "is_shared": view.is_shared})
    if payload.name is not None:
        view.name = payload.name.strip()
    if payload.filters is not None:
        view.filters = payload.filters
    if payload.is_shared is not None:
        if payload.is_shared and not user.is_admin:
            raise ApiError("FORBIDDEN", "Only admins can share views", 403)
        view.is_shared = payload.is_shared
    await session.commit()
    await session.refresh(view)
    await log_activity(
        session,
        user.id,
        "saved_view",
        view.id,
        "saved_view_updated",
        diff_payload(before, slim({"name": view.name})),
    )
    await session.commit()
    return SavedViewOut.model_validate(view)


@router.delete("/{view_id}")
async def delete_saved_view(
    view_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    view = await session.get(CrmSavedView, view_id)
    if view is None:
        raise ApiError("NOT_FOUND", "Saved view not found", 404)
    if not _can_edit(view, user):
        raise ApiError("FORBIDDEN", "Only the owner or an admin can delete this view", 403)
    await log_activity(
        session,
        user.id,
        "saved_view",
        view.id,
        "saved_view_deleted",
        diff_payload(slim({"name": view.name}), None),
    )
    await session.delete(view)
    await session.commit()
    return {"ok": True}
