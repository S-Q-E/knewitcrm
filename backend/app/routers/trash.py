from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_role
from ..deps import get_session, pagination
from ..models import CrmContact, CrmDeal
from ..schemas.contacts_data import TrashItemOut, TrashListOut

router = APIRouter(prefix="/api/trash", tags=["trash"])


@router.get("", response_model=TrashListOut)
async def list_trash(
    kind: str = Query(default="all", pattern="^(all|contact|deal)$"),
    user: CurrentUser = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination),
):
    items: list[TrashItemOut] = []
    total = 0
    if kind in ("all", "contact"):
        stmt = select(CrmContact).where(CrmContact.deleted_at.is_not(None))
        total_c = await _count(session, stmt)
        total += total_c
        if kind == "contact":
            rows = await _page(session, stmt, CrmContact.deleted_at.desc(), page)
            items += [
                TrashItemOut(kind="contact", id=c.id, name=c.name, deleted_at=c.deleted_at)
                for c in rows
            ]
    if kind in ("all", "deal"):
        stmt_d = select(CrmDeal).where(CrmDeal.deleted_at.is_not(None))
        total_d = await _count(session, stmt_d)
        total += total_d
        if kind == "deal":
            rows_d = await _page(session, stmt_d, CrmDeal.deleted_at.desc(), page)
            items += [
                TrashItemOut(kind="deal", id=d.id, name=d.title, deleted_at=d.deleted_at)
                for d in rows_d
            ]
    if kind == "all":
        contacts = await _page(
            session,
            select(CrmContact).where(CrmContact.deleted_at.is_not(None)),
            CrmContact.deleted_at.desc(),
            page,
        )
        deals = await _page(
            session,
            select(CrmDeal).where(CrmDeal.deleted_at.is_not(None)),
            CrmDeal.deleted_at.desc(),
            page,
        )
        merged = sorted(
            [
                TrashItemOut(kind="contact", id=c.id, name=c.name, deleted_at=c.deleted_at)
                for c in contacts
            ]
            + [
                TrashItemOut(kind="deal", id=d.id, name=d.title, deleted_at=d.deleted_at)
                for d in deals
            ],
            key=lambda i: i.deleted_at or "",
            reverse=True,
        )
        items = merged[: page["limit"]]
    return TrashListOut(items=items, total=total)


async def _count(session: AsyncSession, stmt) -> int:
    return (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0


async def _page(session: AsyncSession, stmt, order, page: dict):
    rows = await session.execute(stmt.order_by(order).limit(page["limit"]).offset(page["offset"]))
    return rows.scalars().all()
