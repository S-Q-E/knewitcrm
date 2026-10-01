from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_role
from ..deps import get_session, pagination
from ..models import CrmActivityLog, CrmUser
from ..schemas.settings import ActivityItemOut, ActivityListOut

router = APIRouter(prefix="/api/activity", tags=["activity"])

require_admin = require_role("admin")


@router.get("", response_model=ActivityListOut)
async def list_activity(
    actor_id: uuid.UUID | None = None,
    entity: str | None = Query(default=None, max_length=32),
    action: str | None = Query(default=None, max_length=64),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination),
):
    """Global audit journal (admin). Newest first, with actor names joined."""
    del admin
    stmt = (
        select(CrmActivityLog, CrmUser.name)
        .outerjoin(CrmUser, CrmUser.id == CrmActivityLog.actor_id)
        .order_by(CrmActivityLog.created_at.desc(), CrmActivityLog.id.desc())
    )
    if actor_id is not None:
        stmt = stmt.where(CrmActivityLog.actor_id == actor_id)
    if entity:
        stmt = stmt.where(CrmActivityLog.entity == entity.strip())
    if action:
        stmt = stmt.where(CrmActivityLog.action.ilike(f"%{action.strip()}%"))
    if date_from is not None:
        stmt = stmt.where(CrmActivityLog.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(CrmActivityLog.created_at <= date_to)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (await session.execute(stmt.limit(page["limit"]).offset(page["offset"]))).all()
    return ActivityListOut(
        items=[
            ActivityItemOut(
                id=row.id,
                actor_id=row.actor_id,
                actor_name=name,
                entity=row.entity,
                entity_id=row.entity_id,
                action=row.action,
                diff=row.diff or {},
                created_at=row.created_at,
            )
            for row, name in rows
        ],
        total=total,
    )


@router.get("/entities")
async def list_entities(
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Distinct entity/action values present in the journal (filter dropdowns)."""
    del admin
    entities = (
        (
            await session.execute(
                select(CrmActivityLog.entity).distinct().order_by(CrmActivityLog.entity)
            )
        )
        .scalars()
        .all()
    )
    actions = (
        (
            await session.execute(
                select(CrmActivityLog.action).distinct().order_by(CrmActivityLog.action)
            )
        )
        .scalars()
        .all()
    )
    return {"entities": [str(e) for e in entities], "actions": [str(a) for a in actions]}
