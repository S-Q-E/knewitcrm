from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_role, require_user
from ..deps import get_session, pagination
from ..errors import ApiError
from ..models import CrmDeal, CrmLostReason
from ..schemas.meta import (
    LostReasonCreate,
    LostReasonListOut,
    LostReasonOut,
    LostReasonUpdate,
)
from ..services.activity import diff_payload, log_activity, slim

router = APIRouter(prefix="/api/lost-reasons", tags=["lost-reasons"])

require_admin = require_role("admin")


@router.get("", response_model=LostReasonListOut)
async def list_lost_reasons(
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination),
):
    del user
    total = (await session.execute(select(func.count()).select_from(CrmLostReason))).scalar() or 0
    rows = (
        await session.execute(
            select(CrmLostReason)
            .order_by(CrmLostReason.sort, CrmLostReason.name)
            .limit(page["limit"])
            .offset(page["offset"])
        )
    ).scalars()
    return LostReasonListOut(items=[LostReasonOut.model_validate(r) for r in rows], total=total)


@router.post("", response_model=LostReasonOut, status_code=201)
async def create_lost_reason(
    payload: LostReasonCreate,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    reason = CrmLostReason(name=payload.name.strip(), sort=payload.sort)
    session.add(reason)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError("REASON_EXISTS", "A reason with this name already exists", 409) from exc
    await session.refresh(reason)
    await log_activity(
        session,
        admin.id,
        "lost_reason",
        reason.id,
        "lost_reason_created",
        diff_payload(None, slim({"name": reason.name})),
    )
    await session.commit()
    return LostReasonOut.model_validate(reason)


@router.patch("/{reason_id}", response_model=LostReasonOut)
async def update_lost_reason(
    reason_id: uuid.UUID,
    payload: LostReasonUpdate,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    reason = await session.get(CrmLostReason, reason_id)
    if reason is None:
        raise ApiError("NOT_FOUND", "Lost reason not found", 404)
    before = slim({"name": reason.name, "sort": reason.sort})
    if payload.name is not None:
        reason.name = payload.name.strip()
    if payload.sort is not None:
        reason.sort = payload.sort
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError("REASON_EXISTS", "A reason with this name already exists", 409) from exc
    await session.refresh(reason)
    await log_activity(
        session,
        admin.id,
        "lost_reason",
        reason.id,
        "lost_reason_updated",
        diff_payload(before, slim({"name": reason.name})),
    )
    await session.commit()
    return LostReasonOut.model_validate(reason)


@router.delete("/{reason_id}")
async def delete_lost_reason(
    reason_id: uuid.UUID,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    reason = await session.get(CrmLostReason, reason_id)
    if reason is None:
        raise ApiError("NOT_FOUND", "Lost reason not found", 404)
    used = (
        await session.execute(
            select(func.count()).select_from(CrmDeal).where(CrmDeal.lost_reason_id == reason.id)
        )
    ).scalar()
    if used:
        raise ApiError("REASON_IN_USE", "Reason is used by deals", 409, {"deals": used})
    await log_activity(
        session,
        admin.id,
        "lost_reason",
        reason.id,
        "lost_reason_deleted",
        diff_payload(slim({"name": reason.name}), None),
    )
    await session.delete(reason)
    await session.commit()
    return {"ok": True}
