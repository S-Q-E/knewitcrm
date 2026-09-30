from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_user
from ..deps import get_session, pagination
from ..errors import ApiError
from ..models import (
    DEAL_STATUS_LOST,
    DEAL_STATUS_OPEN,
    DEAL_STATUS_WON,
    ENTITY_DEAL,
    HISTORY_SOURCE_MANAGER,
    CrmContact,
    CrmDeal,
    CrmDealStageHistory,
    CrmEntityTag,
    CrmLostReason,
    CrmPipeline,
    CrmStage,
    CrmUser,
)
from ..schemas.deals import (
    BoardColumnOut,
    BoardOut,
    BulkDealsIn,
    BulkDealsOut,
    DealCreate,
    DealListOut,
    DealMoveIn,
    DealOut,
    DealUpdate,
    TimelineItemOut,
    TimelineOut,
)
from ..schemas.meta import TagOut, TagSetIn
from ..services.activity import diff_payload, log_activity, slim
from ..services.custom_fields import load_definitions, validate_custom_values
from ..services.deal_flow import apply_deal_stage
from ..services.tags import detach_entity_tags, entity_tags_map, replace_entity_tags
from ..services.timeline import get_deal_timeline, parse_cursor, parse_types
from ..services.visibility import (
    ensure_visible,
    is_visible,
    owner_condition,
    restrict_managers_to_own,
)

router = APIRouter(prefix="/api/deals", tags=["deals"])

DEAL_SORTS = {
    "created_at": CrmDeal.created_at,
    "-created_at": CrmDeal.created_at.desc(),
    "updated_at": CrmDeal.updated_at,
    "-updated_at": CrmDeal.updated_at.desc(),
    "position": CrmDeal.position,
    "-position": CrmDeal.position.desc(),
    "amount": CrmDeal.amount,
    "-amount": CrmDeal.amount.desc(),
}

BOARD_ORDER = (CrmDeal.position.asc(), CrmDeal.id.asc())


def _encode_cursor(position: Decimal, deal_id: uuid.UUID) -> str:
    raw = f"{position}:{deal_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[Decimal, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        position_raw, _, id_raw = raw.partition(":")
        return Decimal(position_raw), uuid.UUID(id_raw)
    except (ValueError, ArithmeticError):
        raise ApiError("INVALID_CURSOR", "Board cursor is invalid", 422) from None


def _parse_cursors(raw: str) -> dict[str, str]:
    try:
        parsed = json.loads(raw or "{}")
    except ValueError:
        raise ApiError("INVALID_CURSOR", "cursors must be a JSON object", 422) from None
    if not isinstance(parsed, dict):
        raise ApiError("INVALID_CURSOR", "cursors must be a JSON object", 422)
    return {str(k): str(v) for k, v in parsed.items()}


async def _deal_out(
    session: AsyncSession, deal: CrmDeal, tags: list[TagOut] | None = None
) -> DealOut:
    row = DealOut.model_validate(deal)
    if tags is None:
        tags = (await entity_tags_map(session, ENTITY_DEAL, [deal.id]))[deal.id]
    row.tags = tags
    return row


async def _get_visible(session: AsyncSession, deal_id: uuid.UUID, user: CurrentUser) -> CrmDeal:
    deal = await session.get(CrmDeal, deal_id)
    if deal is None or deal.deleted_at is not None:
        raise ApiError("NOT_FOUND", "Deal not found", 404)
    restricted = await restrict_managers_to_own(session)
    ensure_visible(is_visible(deal.owner_id, user, restricted))
    return deal


async def _require_reason(session: AsyncSession, reason_id: uuid.UUID | None) -> uuid.UUID:
    if reason_id is None:
        raise ApiError("LOST_REASON_REQUIRED", "lost_reason_id is required", 422)
    if await session.get(CrmLostReason, reason_id) is None:
        raise ApiError("UNKNOWN_LOST_REASON", "Lost reason not found", 422)
    return reason_id


def _base_stmt():
    """Deals of live contacts (soft-deleted contacts hide their deals)."""
    return (
        select(CrmDeal)
        .join(CrmContact, CrmContact.id == CrmDeal.contact_id)
        .where(CrmDeal.deleted_at.is_(None), CrmContact.deleted_at.is_(None))
    )


@router.get("", response_model=DealListOut)
async def list_deals(
    pipeline_id: uuid.UUID | None = None,
    stage_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, pattern="^(open|won|lost)$"),
    owner_id: uuid.UUID | None = None,
    unassigned: bool = False,
    tag: list[uuid.UUID] = Query(default=[]),
    lost_reason_id: uuid.UUID | None = None,
    contact_source: str | None = None,
    search: str | None = Query(default=None, max_length=255),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    sort: str = Query(default="-created_at"),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination),
):
    if sort not in DEAL_SORTS:
        raise ApiError("INVALID_SORT", f"sort must be one of {sorted(DEAL_SORTS)}", 422)
    stmt = _base_stmt()
    if pipeline_id is not None:
        stmt = stmt.where(CrmDeal.pipeline_id == pipeline_id)
    if stage_id is not None:
        stmt = stmt.where(CrmDeal.stage_id == stage_id)
    if status is not None:
        stmt = stmt.where(CrmDeal.status == status)
    if owner_id is not None:
        stmt = stmt.where(CrmDeal.owner_id == owner_id)
    if unassigned:
        stmt = stmt.where(CrmDeal.owner_id.is_(None))
    if tag:
        stmt = stmt.where(
            select(CrmEntityTag.entity_id)
            .where(CrmEntityTag.entity == ENTITY_DEAL, CrmEntityTag.tag_id.in_(tag))
            .correlate(CrmDeal)
            .where(CrmEntityTag.entity_id == CrmDeal.id)
            .exists()
        )
    if lost_reason_id is not None:
        stmt = stmt.where(CrmDeal.lost_reason_id == lost_reason_id)
    if contact_source is not None:
        stmt = stmt.where(CrmContact.source == contact_source)
    if search:
        stmt = stmt.where(CrmDeal.title.ilike(f"%{search.strip()}%"))
    if created_from is not None:
        stmt = stmt.where(CrmDeal.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(CrmDeal.created_at <= created_to)
    restricted = await restrict_managers_to_own(session)
    scope = owner_condition(CrmDeal.owner_id, user, restricted)
    if scope is not None:
        stmt = stmt.where(scope)

    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await session.execute(
            stmt.order_by(DEAL_SORTS[sort]).limit(page["limit"]).offset(page["offset"])
        )
    ).scalars()
    items = list(rows)
    tags = await entity_tags_map(session, ENTITY_DEAL, [d.id for d in items])
    return DealListOut(
        items=[await _deal_out(session, d, tags.get(d.id, [])) for d in items], total=total
    )


@router.get("/board", response_model=BoardOut)
async def deal_board(
    pipeline_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    cursors: str = Query(default="{}"),
    owner_id: uuid.UUID | None = None,
    unassigned: bool = False,
    tag: list[uuid.UUID] = Query(default=[]),
    contact_source: str | None = None,
    search: str | None = Query(default=None, max_length=255),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    pipeline = await session.get(CrmPipeline, pipeline_id)
    if pipeline is None:
        raise ApiError("NOT_FOUND", "Pipeline not found", 404)
    cursor_map = _parse_cursors(cursors)
    restricted = await restrict_managers_to_own(session)
    scope = owner_condition(CrmDeal.owner_id, user, restricted)
    stages = (
        await session.execute(
            select(CrmStage)
            .where(CrmStage.pipeline_id == pipeline.id)
            .order_by(CrmStage.sort, CrmStage.name)
        )
    ).scalars()
    columns = []
    for stage in stages:
        filters = [
            CrmDeal.pipeline_id == pipeline.id,
            CrmDeal.stage_id == stage.id,
            CrmDeal.deleted_at.is_(None),
        ]
        if scope is not None:
            filters.append(scope)
        if owner_id is not None:
            filters.append(CrmDeal.owner_id == owner_id)
        if unassigned:
            filters.append(CrmDeal.owner_id.is_(None))
        if tag:
            filters.append(
                select(CrmEntityTag.entity_id)
                .where(CrmEntityTag.entity == ENTITY_DEAL, CrmEntityTag.tag_id.in_(tag))
                .correlate(CrmDeal)
                .where(CrmEntityTag.entity_id == CrmDeal.id)
                .exists()
            )
        if search:
            filters.append(CrmDeal.title.ilike(f"%{search.strip()}%"))
        if created_from is not None:
            filters.append(CrmDeal.created_at >= created_from)
        if created_to is not None:
            filters.append(CrmDeal.created_at <= created_to)
        contact_conditions = [
            CrmContact.id == CrmDeal.contact_id,
            CrmContact.deleted_at.is_(None),
        ]
        if contact_source is not None:
            contact_conditions.append(CrmContact.source == contact_source)
        contact_scope = select(CrmContact.id).where(*contact_conditions)
        base = select(CrmDeal).where(*filters, contact_scope.exists())
        total = (
            await session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar() or 0
        amount_total = (
            await session.execute(
                select(func.coalesce(func.sum(CrmDeal.amount), 0)).select_from(base.subquery())
            )
        ).scalar() or 0

        page_stmt = base.order_by(*BOARD_ORDER)
        if str(stage.id) in cursor_map:
            pos, last_id = _decode_cursor(cursor_map[str(stage.id)])
            page_stmt = page_stmt.where(
                or_(CrmDeal.position > pos, (CrmDeal.position == pos) & (CrmDeal.id > last_id))
            )
        rows = (await session.execute(page_stmt.limit(limit + 1))).scalars()
        items = list(rows)
        next_cursor = None
        if len(items) > limit:
            items = items[:limit]
            next_cursor = _encode_cursor(items[-1].position, items[-1].id)
        tags = await entity_tags_map(session, ENTITY_DEAL, [d.id for d in items])
        columns.append(
            BoardColumnOut(
                stage_id=stage.id,
                name=stage.name,
                kind=stage.kind,
                total=total,
                amount_total=float(amount_total),
                items=[await _deal_out(session, d, tags.get(d.id, [])) for d in items],
                next_cursor=next_cursor,
            )
        )
    return BoardOut(pipeline_id=pipeline.id, columns=columns)


@router.post("", response_model=DealOut, status_code=201)
async def create_deal(
    payload: DealCreate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    contact = await session.get(CrmContact, payload.contact_id)
    if contact is None or contact.deleted_at is not None:
        raise ApiError("UNKNOWN_CONTACT", "Contact not found", 422)
    pipeline = await session.get(CrmPipeline, payload.pipeline_id)
    if pipeline is None:
        raise ApiError("UNKNOWN_PIPELINE", "Pipeline not found", 422)
    stage = await session.get(CrmStage, payload.stage_id)
    if stage is None or stage.pipeline_id != pipeline.id:
        raise ApiError("UNKNOWN_STAGE", "Stage not found in this pipeline", 422)
    if stage.kind != "open":
        raise ApiError("STAGE_CLOSED", "New deals can only be created in open stages", 422)
    if payload.owner_id is not None and await session.get(CrmUser, payload.owner_id) is None:
        raise ApiError("UNKNOWN_OWNER", "Owner not found", 422)
    definitions = await load_definitions(session, ENTITY_DEAL)
    validate_custom_values(ENTITY_DEAL, payload.custom, definitions)
    top = (
        await session.execute(
            select(func.max(CrmDeal.position)).where(
                CrmDeal.stage_id == stage.id, CrmDeal.deleted_at.is_(None)
            )
        )
    ).scalar()
    deal = CrmDeal(
        contact_id=contact.id,
        pipeline_id=pipeline.id,
        stage_id=stage.id,
        title=payload.title.strip(),
        amount=payload.amount,
        currency=payload.currency.upper(),
        owner_id=payload.owner_id,
        status=DEAL_STATUS_OPEN,
        trial_at=payload.trial_at,
        position=(top or Decimal(0)) + 1,
        custom=payload.custom,
    )
    session.add(deal)
    await session.flush()
    session.add(
        CrmDealStageHistory(
            deal_id=deal.id,
            from_stage_id=None,
            to_stage_id=stage.id,
            changed_by=user.id,
            source=HISTORY_SOURCE_MANAGER,
        )
    )
    await log_activity(
        session,
        user.id,
        "deal",
        deal.id,
        "deal_created",
        diff_payload(None, slim({"title": deal.title, "stage_id": deal.stage_id})),
    )
    await session.commit()
    await session.refresh(deal)
    return await _deal_out(session, deal, [])


@router.get("/{deal_id}", response_model=DealOut)
async def get_deal(
    deal_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    return await _deal_out(session, await _get_visible(session, deal_id, user))


@router.patch("/{deal_id}", response_model=DealOut)
async def update_deal(
    deal_id: uuid.UUID,
    payload: DealUpdate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    deal = await _get_visible(session, deal_id, user)
    before = slim(
        {
            "title": deal.title,
            "amount": deal.amount,
            "currency": deal.currency,
            "owner_id": deal.owner_id,
            "status": deal.status,
            "lost_reason_id": deal.lost_reason_id,
            "custom": deal.custom,
        }
    )
    if payload.owner_id is not None and await session.get(CrmUser, payload.owner_id) is None:
        raise ApiError("UNKNOWN_OWNER", "Owner not found", 422)
    if payload.title is not None:
        deal.title = payload.title.strip()
    if payload.amount is not None:
        deal.amount = payload.amount
    if payload.currency is not None:
        deal.currency = payload.currency.upper()
    if payload.owner_id is not None:
        deal.owner_id = payload.owner_id
    if payload.trial_at is not None:
        deal.trial_at = payload.trial_at
    if payload.lost_reason_id is not None:
        await _require_reason(session, payload.lost_reason_id)
        deal.lost_reason_id = payload.lost_reason_id
    if payload.status is not None and payload.status != deal.status:
        if payload.status == DEAL_STATUS_LOST:
            deal.lost_reason_id = await _require_reason(
                session,
                payload.lost_reason_id
                if payload.lost_reason_id is not None
                else deal.lost_reason_id,
            )
            deal.closed_at = datetime.now(UTC)
        elif payload.status == DEAL_STATUS_WON:
            deal.lost_reason_id = None
            deal.closed_at = datetime.now(UTC)
        else:
            deal.lost_reason_id = None
            deal.closed_at = None
        deal.status = payload.status
    if payload.custom is not None:
        definitions = await load_definitions(session, ENTITY_DEAL)
        validate_custom_values(ENTITY_DEAL, payload.custom, definitions)
        deal.custom = payload.custom
    await session.commit()
    await session.refresh(deal)
    await log_activity(
        session,
        user.id,
        "deal",
        deal.id,
        "deal_updated",
        diff_payload(
            before, slim({"title": deal.title, "status": deal.status, "custom": deal.custom})
        ),
    )
    await session.commit()
    return await _deal_out(session, deal)


@router.delete("/{deal_id}")
async def delete_deal(
    deal_id: uuid.UUID,
    hard: bool = False,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    if hard and not user.is_admin:
        raise ApiError("FORBIDDEN", "Only admins can hard-delete", 403)
    deal = await session.get(CrmDeal, deal_id)
    if deal is None:
        raise ApiError("NOT_FOUND", "Deal not found", 404)
    if not user.is_admin:
        restricted = await restrict_managers_to_own(session)
        ensure_visible(is_visible(deal.owner_id, user, restricted))
    if hard:
        await detach_entity_tags(session, ENTITY_DEAL, deal.id)
        await log_activity(
            session,
            user.id,
            "deal",
            deal.id,
            "deal_hard_deleted",
            diff_payload(slim({"title": deal.title}), None),
        )
        await session.delete(deal)
        await session.commit()
        return {"ok": True, "hard": True}
    if deal.deleted_at is None:
        deal.deleted_at = datetime.now(UTC)
        await log_activity(session, user.id, "deal", deal.id, "deal_deleted", {"deleted": True})
        await session.commit()
    return {"ok": True, "hard": False}


@router.post("/{deal_id}/restore", response_model=DealOut)
async def restore_deal(
    deal_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    deal = await session.get(CrmDeal, deal_id)
    if deal is None:
        raise ApiError("NOT_FOUND", "Deal not found", 404)
    restricted = await restrict_managers_to_own(session)
    ensure_visible(is_visible(deal.owner_id, user, restricted))
    deal.deleted_at = None
    await session.commit()
    await session.refresh(deal)
    await log_activity(session, user.id, "deal", deal.id, "deal_restored", {"restored": True})
    await session.commit()
    return await _deal_out(session, deal)


@router.post("/{deal_id}/move", response_model=DealOut)
async def move_deal(
    deal_id: uuid.UUID,
    payload: DealMoveIn,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    deal = await _get_visible(session, deal_id, user)
    target = await session.get(CrmStage, payload.stage_id)
    if target is None:
        raise ApiError("UNKNOWN_STAGE", "Stage not found", 422)
    contact = await session.get(CrmContact, deal.contact_id)
    result = await apply_deal_stage(
        session,
        deal,
        target,
        contact.whatsapp_id if contact else None,
        actor_id=user.id,
        source=HISTORY_SOURCE_MANAGER,
        position=payload.position,
        lost_reason_id=payload.lost_reason_id,
    )
    await session.flush()
    await log_activity(
        session,
        user.id,
        "deal",
        deal.id,
        "deal_moved",
        {"to_stage_id": str(target.id), "bridged": result["bridged"]},
    )
    await session.commit()
    await session.refresh(deal)
    return await _deal_out(session, deal)


@router.post("/{deal_id}/unlock-bot", response_model=DealOut)
async def unlock_bot(
    deal_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    deal = await _get_visible(session, deal_id, user)
    deal.stage_locked = False
    await session.flush()
    await log_activity(session, user.id, "deal", deal.id, "deal_unlocked", {"stage_locked": False})
    await session.commit()
    await session.refresh(deal)
    return await _deal_out(session, deal)


@router.put("/{deal_id}/tags", response_model=list[TagOut])
async def set_deal_tags(
    deal_id: uuid.UUID,
    payload: TagSetIn,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    deal = await _get_visible(session, deal_id, user)
    tags = await replace_entity_tags(session, ENTITY_DEAL, deal.id, payload.tag_ids)
    await log_activity(
        session,
        user.id,
        "deal",
        deal.id,
        "deal_tags_set",
        {"tag_ids": [str(t.id) for t in tags]},
    )
    await session.commit()
    return tags


@router.post("/bulk", response_model=BulkDealsOut)
async def bulk_update_deals(
    payload: BulkDealsIn,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    if (
        payload.set_owner_id is None
        and payload.set_stage_id is None
        and payload.add_tag_id is None
        and payload.close_lost_reason_id is None
    ):
        raise ApiError("EMPTY_BULK", "At least one bulk operation is required", 422)
    target_stage = None
    if payload.set_stage_id is not None:
        target_stage = await session.get(CrmStage, payload.set_stage_id)
        if target_stage is None:
            raise ApiError("UNKNOWN_STAGE", "Stage not found", 422)
    if (
        payload.set_owner_id is not None
        and await session.get(CrmUser, payload.set_owner_id) is None
    ):
        raise ApiError("UNKNOWN_OWNER", "Owner not found", 422)
    add_tag = None
    if payload.add_tag_id is not None:
        from ..models import CrmTag

        add_tag = await session.get(CrmTag, payload.add_tag_id)
        if add_tag is None:
            raise ApiError("UNKNOWN_TAG", "Tag not found", 422)
    if payload.close_lost_reason_id is not None:
        await _require_reason(session, payload.close_lost_reason_id)

    deals = (
        await session.execute(
            select(CrmDeal).where(CrmDeal.id.in_(payload.ids), CrmDeal.deleted_at.is_(None))
        )
    ).scalars()
    by_id = {d.id: d for d in deals}
    missing = set(payload.ids) - set(by_id)
    if missing:
        raise ApiError(
            "BULK_NOT_FOUND",
            "Some deals were not found",
            404,
            {"ids": [str(i) for i in missing]},
        )
    restricted = await restrict_managers_to_own(session)
    contacts = {
        c.id: c
        for c in (
            await session.execute(
                select(CrmContact).where(CrmContact.id.in_([d.contact_id for d in by_id.values()]))
            )
        ).scalars()
    }
    for deal in by_id.values():
        ensure_visible(is_visible(deal.owner_id, user, restricted))
        if payload.set_owner_id is not None:
            deal.owner_id = payload.set_owner_id
        if target_stage is not None:
            contact = contacts.get(deal.contact_id)
            await apply_deal_stage(
                session,
                deal,
                target_stage,
                contact.whatsapp_id if contact else None,
                actor_id=user.id,
                source=HISTORY_SOURCE_MANAGER,
                position=payload.set_position,
            )
        if add_tag is not None:
            exists = (
                await session.execute(
                    select(CrmEntityTag.id).where(
                        CrmEntityTag.entity == ENTITY_DEAL,
                        CrmEntityTag.entity_id == deal.id,
                        CrmEntityTag.tag_id == add_tag.id,
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                session.add(CrmEntityTag(tag_id=add_tag.id, entity=ENTITY_DEAL, entity_id=deal.id))
        if payload.close_lost_reason_id is not None:
            deal.status = DEAL_STATUS_LOST
            deal.lost_reason_id = payload.close_lost_reason_id
            deal.closed_at = datetime.now(UTC)
    await session.flush()
    for deal in by_id.values():
        await log_activity(session, user.id, "deal", deal.id, "deal_bulk_updated", {})
    await session.commit()
    return BulkDealsOut(updated=len(by_id))


@router.get("/{deal_id}/timeline", response_model=TimelineOut)
async def deal_timeline(
    deal_id: uuid.UUID,
    types: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=500),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Unified newest-first stream: messages, events, stages, notes, tasks, activity."""
    deal = await _get_visible(session, deal_id, user)
    contact = await session.get(CrmContact, deal.contact_id)
    kinds = parse_types(types)
    position = parse_cursor(cursor)
    items, next_cursor = await get_deal_timeline(
        session,
        deal.id,
        deal.contact_id,
        contact.whatsapp_id if contact else None,
        contact.name if contact else None,
        kinds,
        limit,
        position,
    )
    out = []
    for item in items:
        at = datetime.fromisoformat(item["at"])
        data = {k: v for k, v in item.items() if k not in ("key", "kind", "at", "ref")}
        out.append(TimelineItemOut(key=item["key"], kind=item["kind"], at=at, data=data))
    return TimelineOut(items=out, next_cursor=next_cursor)
