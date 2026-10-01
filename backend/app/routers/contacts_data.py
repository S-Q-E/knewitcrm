from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_user
from ..deps import get_session, pagination
from ..errors import ApiError
from ..models import (
    ENTITY_CONTACT,
    CrmContact,
    CrmDeal,
    CrmTag,
    CrmUser,
)
from ..schemas.contacts import ContactOut
from ..schemas.contacts_data import (
    BulkContactsIn,
    BulkContactsOut,
    ContactTimelineItemOut,
    ContactTimelineOut,
    DuplicateGroupOut,
    DuplicateListOut,
    MergeContactsIn,
)
from ..schemas.deals import DealListOut
from ..services.activity import log_activity
from ..services.deals_serialize import deals_out
from ..services.duplicates import find_duplicate_groups, merge_contacts
from ..services.tags import entity_tags_map
from ..services.timeline import get_contact_timeline, parse_cursor, parse_types
from ..services.visibility import (
    ensure_visible,
    is_visible,
    restrict_managers_to_own,
)

router = APIRouter(prefix="/api/contacts", tags=["contacts-data"])


@router.get("/duplicates", response_model=DuplicateListOut)
async def list_duplicates(
    limit: int = Query(default=100, ge=1, le=500),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    groups = await find_duplicate_groups(session, limit=limit)
    restricted = await restrict_managers_to_own(session)
    if restricted and not user.is_admin:
        visible_groups = []
        for group in groups:
            stmt = select(CrmContact).where(CrmContact.id.in_(group["contact_ids"]))
            contacts = (await session.execute(stmt)).scalars().all()
            if all(is_visible(c.owner_id, user, restricted) for c in contacts):
                visible_groups.append(group)
        groups = visible_groups
    return DuplicateListOut(
        groups=[DuplicateGroupOut(**g) for g in groups],
        total=len(groups),
    )


@router.post("/merge", response_model=ContactOut)
async def merge_contacts_endpoint(
    payload: MergeContactsIn,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    restricted = await restrict_managers_to_own(session)
    winner = await merge_contacts(
        session,
        payload.winner_id,
        payload.loser_id,
        actor_id=user.id,
        actor_is_admin=user.is_admin,
        restricted=restricted,
        actor_user_id=user.id,
    )
    row = ContactOut.model_validate(winner)
    row.tags = (await entity_tags_map(session, ENTITY_CONTACT, [winner.id]))[winner.id]
    return row


@router.post("/bulk", response_model=BulkContactsOut)
async def bulk_update_contacts(
    payload: BulkContactsIn,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    if payload.set_owner_id is None and payload.add_tag_id is None and not payload.delete:
        raise ApiError("EMPTY_BULK", "At least one bulk operation is required", 422)
    if payload.set_owner_id is not None:
        owner = await session.get(CrmUser, payload.set_owner_id)
        if owner is None:
            raise ApiError("UNKNOWN_OWNER", "Owner not found", 422)
    add_tag: CrmTag | None = None
    if payload.add_tag_id is not None:
        add_tag = await session.get(CrmTag, payload.add_tag_id)
        if add_tag is None:
            raise ApiError("UNKNOWN_TAG", "Tag not found", 422)
    contacts = (
        (await session.execute(select(CrmContact).where(CrmContact.id.in_(payload.ids))))
        .scalars()
        .all()
    )
    by_id = {c.id: c for c in contacts}
    missing = set(payload.ids) - set(by_id)
    if missing:
        raise ApiError(
            "BULK_NOT_FOUND",
            "Some contacts were not found",
            404,
            {"ids": [str(i) for i in missing]},
        )
    restricted = await restrict_managers_to_own(session)
    for contact in by_id.values():
        ensure_visible(is_visible(contact.owner_id, user, restricted))
        if contact.deleted_at is not None:
            raise ApiError(
                "BULK_DELETED",
                "Some contacts are deleted",
                409,
                {"ids": [str(contact.id)]},
            )
        if payload.set_owner_id is not None:
            contact.owner_id = payload.set_owner_id
        if add_tag is not None:
            from ..models import CrmEntityTag

            exists = (
                await session.execute(
                    select(CrmEntityTag.id).where(
                        CrmEntityTag.entity == ENTITY_CONTACT,
                        CrmEntityTag.entity_id == contact.id,
                        CrmEntityTag.tag_id == add_tag.id,
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                session.add(
                    CrmEntityTag(
                        tag_id=add_tag.id, entity=ENTITY_CONTACT, entity_id=contact.id
                    )
                )
        if payload.delete:
            contact.deleted_at = datetime.now(UTC)
    await session.flush()
    for contact in by_id.values():
        await log_activity(session, user.id, "contact", contact.id, "contact_bulk_updated", {})
    await session.commit()
    return BulkContactsOut(updated=len(by_id))


@router.get("/{contact_id}/deals", response_model=DealListOut)
async def contact_deals(
    contact_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination),
):
    contact = await session.get(CrmContact, contact_id)
    if contact is None or contact.deleted_at is not None:
        raise ApiError("NOT_FOUND", "Contact not found", 404)
    restricted = await restrict_managers_to_own(session)
    ensure_visible(is_visible(contact.owner_id, user, restricted))
    stmt = select(CrmDeal).where(
        CrmDeal.contact_id == contact.id, CrmDeal.deleted_at.is_(None)
    )
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await session.execute(
            stmt.order_by(CrmDeal.updated_at.desc()).limit(page["limit"]).offset(page["offset"])
        )
    ).scalars().all()
    return DealListOut(items=await deals_out(session, list(rows)), total=total)


@router.get("/{contact_id}/timeline", response_model=ContactTimelineOut)
async def contact_timeline(
    contact_id: uuid.UUID,
    types: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=500),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    contact = await session.get(CrmContact, contact_id)
    if contact is None or contact.deleted_at is not None:
        raise ApiError("NOT_FOUND", "Contact not found", 404)
    restricted = await restrict_managers_to_own(session)
    ensure_visible(is_visible(contact.owner_id, user, restricted))
    kinds = parse_types(types)
    position = parse_cursor(cursor)
    items, next_cursor = await get_contact_timeline(
        session, contact.id, contact.whatsapp_id, contact.name, kinds, limit, position
    )
    out = []
    for item in items:
        at = datetime.fromisoformat(item["at"])
        data = {k: v for k, v in item.items() if k not in ("key", "kind", "at", "ref")}
        out.append(ContactTimelineItemOut(key=item["key"], kind=item["kind"], at=at, data=data))
    return ContactTimelineOut(items=out, next_cursor=next_cursor)
