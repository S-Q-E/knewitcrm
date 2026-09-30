from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_role, require_user
from ..deps import get_session, pagination
from ..errors import ApiError
from ..models import CrmEntityTag, CrmTag
from ..schemas.meta import TagCreate, TagListOut, TagOut, TagUpdate
from ..services.activity import diff_payload, log_activity, slim

router = APIRouter(prefix="/api/tags", tags=["tags"])

require_admin = require_role("admin")


@router.get("", response_model=TagListOut)
async def list_tags(
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination),
):
    del user
    total = (await session.execute(select(func.count()).select_from(CrmTag))).scalar() or 0
    rows = (
        await session.execute(
            select(CrmTag).order_by(CrmTag.name).limit(page["limit"]).offset(page["offset"])
        )
    ).scalars()
    return TagListOut(items=[TagOut.model_validate(t) for t in rows], total=total)


@router.post("", response_model=TagOut, status_code=201)
async def create_tag(
    payload: TagCreate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    tag = CrmTag(name=payload.name.strip(), color=payload.color)
    session.add(tag)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError("TAG_EXISTS", "A tag with this name already exists", 409) from exc
    await session.refresh(tag)
    await log_activity(
        session,
        user.id,
        "tag",
        tag.id,
        "tag_created",
        diff_payload(None, slim({"name": tag.name})),
    )
    await session.commit()
    return TagOut.model_validate(tag)


@router.patch("/{tag_id}", response_model=TagOut)
async def update_tag(
    tag_id: uuid.UUID,
    payload: TagUpdate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    tag = await session.get(CrmTag, tag_id)
    if tag is None:
        raise ApiError("NOT_FOUND", "Tag not found", 404)
    before = slim({"name": tag.name, "color": tag.color})
    if payload.name is not None:
        tag.name = payload.name.strip()
    if payload.color is not None:
        tag.color = payload.color
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError("TAG_EXISTS", "A tag with this name already exists", 409) from exc
    await session.refresh(tag)
    await log_activity(
        session,
        user.id,
        "tag",
        tag.id,
        "tag_updated",
        diff_payload(before, slim({"name": tag.name})),
    )
    await session.commit()
    return TagOut.model_validate(tag)


@router.delete("/{tag_id}")
async def delete_tag(
    tag_id: uuid.UUID,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    tag = await session.get(CrmTag, tag_id)
    if tag is None:
        raise ApiError("NOT_FOUND", "Tag not found", 404)
    used = (
        await session.execute(
            select(func.count()).select_from(CrmEntityTag).where(CrmEntityTag.tag_id == tag.id)
        )
    ).scalar()
    await log_activity(
        session,
        admin.id,
        "tag",
        tag.id,
        "tag_deleted",
        diff_payload(slim({"name": tag.name}), None),
    )
    await session.delete(tag)
    await session.commit()
    return {"ok": True, "detached_from": used or 0}
