from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_user
from ..deps import get_session, pagination
from ..errors import ApiError
from ..models import CrmNotification

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    unread_only: bool = False,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination),
):
    stmt = select(CrmNotification).where(CrmNotification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(CrmNotification.read_at.is_(None))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    unread_total = (
        await session.execute(
            select(func.count())
            .select_from(CrmNotification)
            .where(CrmNotification.user_id == user.id, CrmNotification.read_at.is_(None))
        )
    ).scalar() or 0
    rows = (
        await session.execute(
            stmt.order_by(CrmNotification.created_at.desc())
            .limit(page["limit"])
            .offset(page["offset"])
        )
    ).scalars()
    return {
        "items": [
            {
                "id": str(row.id),
                "type": row.type,
                "payload": row.payload,
                "read_at": row.read_at.isoformat() if row.read_at else None,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
        "total": total,
        "unread_total": unread_total,
    }


@router.post("/{notification_id}/read")
async def read_notification(
    notification_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(CrmNotification, notification_id)
    if row is None or row.user_id != user.id:
        raise ApiError("NOT_FOUND", "Notification not found", 404)
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
        await session.commit()
    return {"ok": True}


@router.post("/read-all")
async def read_all_notifications(
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        update(CrmNotification)
        .where(CrmNotification.user_id == user.id, CrmNotification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    await session.commit()
    return {"ok": True, "marked": result.rowcount or 0}
