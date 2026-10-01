from __future__ import annotations

import json
import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_user
from ..deps import get_session, pagination
from ..errors import ApiError
from ..models import ENTITY_CONTACT, CrmContact, CrmEntityTag
from ..schemas.contacts import ContactCreate, ContactListOut, ContactOut, ContactUpdate
from ..schemas.meta import TagOut, TagSetIn
from ..services.activity import diff_payload, log_activity, slim
from ..services.custom_fields import load_definitions, validate_custom_values
from ..services.tags import detach_entity_tags, entity_tags_map, replace_entity_tags
from ..services.visibility import (
    ensure_visible,
    is_visible,
    owner_condition,
    restrict_managers_to_own,
)

router = APIRouter(prefix="/api/contacts", tags=["contacts"])

CONTACT_SORTS = {
    "created_at": CrmContact.created_at,
    "-created_at": CrmContact.created_at.desc(),
    "updated_at": CrmContact.updated_at,
    "-updated_at": CrmContact.updated_at.desc(),
    "name": CrmContact.name,
    "-name": CrmContact.name.desc(),
}


def normalize_phone(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _parse_custom_filters(raw: list[str]) -> dict[str, object]:
    """Parse repeatable ?custom=key:value params; value is JSON or plain string."""
    out: dict[str, object] = {}
    for item in raw:
        if ":" not in item:
            raise ApiError("INVALID_CUSTOM_FILTER", "Use ?custom=key:value", 422, {"got": item})
        key, _, value = item.partition(":")
        key = key.strip()
        if not key:
            raise ApiError("INVALID_CUSTOM_FILTER", "Use ?custom=key:value", 422, {"got": item})
        try:
            out[key] = json.loads(value)
        except (ValueError, TypeError):
            out[key] = value
    return out


@router.get("", response_model=ContactListOut)
async def list_contacts(
    search: str | None = Query(default=None, max_length=255),
    tag: list[uuid.UUID] = Query(default=[]),
    owner_id: uuid.UUID | None = None,
    unassigned: bool = False,
    source: str | None = None,
    custom: list[str] = Query(default=[]),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    include_deleted: bool = False,
    sort: str = Query(default="-created_at"),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination),
):
    if sort not in CONTACT_SORTS:
        raise ApiError("INVALID_SORT", f"sort must be one of {sorted(CONTACT_SORTS)}", 422)
    stmt = select(CrmContact)
    if not include_deleted:
        stmt = stmt.where(CrmContact.deleted_at.is_(None))
    if search:
        term = f"%{search.strip()}%"
        digits = normalize_phone(search)
        conditions = [
            CrmContact.name.ilike(term),
            CrmContact.phone.ilike(term),
            CrmContact.email.ilike(term),
            CrmContact.whatsapp_id.ilike(term),
        ]
        if len(digits) >= 4:
            conditions.append(
                func.regexp_replace(CrmContact.phone, r"\D", "", "g").like(f"%{digits}%")
            )
        stmt = stmt.where(or_(*conditions))
    if tag:
        stmt = stmt.where(
            select(CrmEntityTag.entity_id)
            .where(CrmEntityTag.entity == ENTITY_CONTACT, CrmEntityTag.tag_id.in_(tag))
            .correlate(CrmContact)
            .where(CrmEntityTag.entity_id == CrmContact.id)
            .exists()
        )
    if owner_id is not None:
        stmt = stmt.where(CrmContact.owner_id == owner_id)
    if unassigned:
        stmt = stmt.where(CrmContact.owner_id.is_(None))
    if source is not None:
        stmt = stmt.where(CrmContact.source == source)
    for key, value in _parse_custom_filters(custom).items():
        stmt = stmt.where(CrmContact.custom[key] == cast(json.dumps(value), JSONB))
    if created_from is not None:
        stmt = stmt.where(CrmContact.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(CrmContact.created_at <= created_to)
    restricted = await restrict_managers_to_own(session)
    scope = owner_condition(CrmContact.owner_id, user, restricted)
    if scope is not None:
        stmt = stmt.where(scope)

    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await session.execute(
            stmt.order_by(CONTACT_SORTS[sort]).limit(page["limit"]).offset(page["offset"])
        )
    ).scalars()
    items = list(rows)
    tags = await entity_tags_map(session, ENTITY_CONTACT, [c.id for c in items])
    out = []
    for contact in items:
        row = ContactOut.model_validate(contact)
        row.tags = tags.get(contact.id, [])
        out.append(row)
    return ContactListOut(items=out, total=total)


@router.post("", response_model=ContactOut, status_code=201)
async def create_contact(
    payload: ContactCreate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    definitions = await load_definitions(session, ENTITY_CONTACT)
    validate_custom_values(ENTITY_CONTACT, payload.custom, definitions)
    if payload.owner_id is not None:
        from ..models import CrmUser

        if await session.get(CrmUser, payload.owner_id) is None:
            raise ApiError("UNKNOWN_OWNER", "Owner not found", 422)
    contact = CrmContact(
        whatsapp_id=payload.whatsapp_id,
        name=payload.name,
        phone=payload.phone,
        email=payload.email,
        source=payload.source,
        owner_id=payload.owner_id,
        custom=payload.custom,
    )
    session.add(contact)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError("WHATSAPP_TAKEN", "Contact with this whatsapp_id exists", 409) from exc
    await session.refresh(contact)
    await log_activity(
        session,
        user.id,
        "contact",
        contact.id,
        "contact_created",
        diff_payload(None, slim({"name": contact.name, "whatsapp_id": contact.whatsapp_id})),
    )
    await session.commit()
    row = ContactOut.model_validate(contact)
    row.tags = []
    return row


async def _get_visible(
    session: AsyncSession, contact_id: uuid.UUID, user: CurrentUser
) -> CrmContact:
    contact = await session.get(CrmContact, contact_id)
    if contact is None or contact.deleted_at is not None:
        raise ApiError("NOT_FOUND", "Contact not found", 404)
    restricted = await restrict_managers_to_own(session)
    ensure_visible(is_visible(contact.owner_id, user, restricted))
    return contact


@router.get("/{contact_id}", response_model=ContactOut)
async def get_contact(
    contact_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    contact = await _get_visible(session, contact_id, user)
    row = ContactOut.model_validate(contact)
    row.tags = (await entity_tags_map(session, ENTITY_CONTACT, [contact.id]))[contact.id]
    return row


@router.patch("/{contact_id}", response_model=ContactOut)
async def update_contact(
    contact_id: uuid.UUID,
    payload: ContactUpdate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    contact = await _get_visible(session, contact_id, user)
    before = slim(
        {
            "name": contact.name,
            "phone": contact.phone,
            "email": contact.email,
            "owner_id": contact.owner_id,
            "custom": contact.custom,
        }
    )
    if "owner_id" in payload.model_fields_set:
        if payload.owner_id is not None:
            from ..models import CrmUser

            if await session.get(CrmUser, payload.owner_id) is None:
                raise ApiError("UNKNOWN_OWNER", "Owner not found", 422)
        contact.owner_id = payload.owner_id
    for field in ("name", "phone", "email", "source"):
        value = getattr(payload, field)
        if value is not None:
            setattr(contact, field, value)
    if payload.custom is not None:
        definitions = await load_definitions(session, ENTITY_CONTACT)
        validate_custom_values(ENTITY_CONTACT, payload.custom, definitions)
        contact.custom = payload.custom
    await session.commit()
    await session.refresh(contact)
    await log_activity(
        session,
        user.id,
        "contact",
        contact.id,
        "contact_updated",
        diff_payload(before, slim({"name": contact.name, "custom": contact.custom})),
    )
    await session.commit()
    row = ContactOut.model_validate(contact)
    row.tags = (await entity_tags_map(session, ENTITY_CONTACT, [contact.id]))[contact.id]
    return row


@router.delete("/{contact_id}")
async def delete_contact(
    contact_id: uuid.UUID,
    hard: bool = False,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    from datetime import UTC, datetime

    if hard and not user.is_admin:
        raise ApiError("FORBIDDEN", "Only admins can hard-delete", 403)
    contact = await session.get(CrmContact, contact_id)
    if contact is None:
        raise ApiError("NOT_FOUND", "Contact not found", 404)
    if not user.is_admin:
        restricted = await restrict_managers_to_own(session)
        ensure_visible(is_visible(contact.owner_id, user, restricted))
    if hard:
        await detach_entity_tags(session, ENTITY_CONTACT, contact.id)
        await log_activity(
            session,
            user.id,
            "contact",
            contact.id,
            "contact_hard_deleted",
            diff_payload(slim({"name": contact.name}), None),
        )
        await session.delete(contact)
        await session.commit()
        return {"ok": True, "hard": True}
    if contact.deleted_at is None:
        contact.deleted_at = datetime.now(UTC)
        await log_activity(
            session, user.id, "contact", contact.id, "contact_deleted", {"deleted": True}
        )
        await session.commit()
    return {"ok": True, "hard": False}


@router.post("/{contact_id}/restore", response_model=ContactOut)
async def restore_contact(
    contact_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    contact = await session.get(CrmContact, contact_id)
    if contact is None:
        raise ApiError("NOT_FOUND", "Contact not found", 404)
    restricted = await restrict_managers_to_own(session)
    ensure_visible(is_visible(contact.owner_id, user, restricted))
    contact.deleted_at = None
    await session.commit()
    await session.refresh(contact)
    await log_activity(
        session, user.id, "contact", contact.id, "contact_restored", {"restored": True}
    )
    await session.commit()
    row = ContactOut.model_validate(contact)
    row.tags = (await entity_tags_map(session, ENTITY_CONTACT, [contact.id]))[contact.id]
    return row


@router.put("/{contact_id}/tags", response_model=list[TagOut])
async def set_contact_tags(
    contact_id: uuid.UUID,
    payload: TagSetIn,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    contact = await _get_visible(session, contact_id, user)
    tags = await replace_entity_tags(session, ENTITY_CONTACT, contact.id, payload.tag_ids)
    await log_activity(
        session,
        user.id,
        "contact",
        contact.id,
        "contact_tags_set",
        {"tag_ids": [str(t.id) for t in tags]},
    )
    await session.commit()
    return tags
