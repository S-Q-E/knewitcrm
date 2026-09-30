from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_role, require_user
from ..deps import get_session, pagination
from ..errors import ApiError
from ..models import CrmCustomField
from ..schemas.meta import (
    CustomFieldCreate,
    CustomFieldListOut,
    CustomFieldOut,
    CustomFieldUpdate,
)
from ..services.activity import diff_payload, log_activity, slim
from ..services.custom_fields import validate_field_definition_key

router = APIRouter(prefix="/api/custom-fields", tags=["custom-fields"])

require_admin = require_role("admin")


@router.get("", response_model=CustomFieldListOut)
async def list_custom_fields(
    entity: str | None = Query(default=None, pattern="^(contact|deal)$"),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination),
):
    del user
    stmt = select(CrmCustomField)
    if entity is not None:
        stmt = stmt.where(CrmCustomField.entity == entity)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await session.execute(
            stmt.order_by(CrmCustomField.sort, CrmCustomField.label)
            .limit(page["limit"])
            .offset(page["offset"])
        )
    ).scalars()
    return CustomFieldListOut(items=[CustomFieldOut.model_validate(f) for f in rows], total=total)


@router.post("", response_model=CustomFieldOut, status_code=201)
async def create_custom_field(
    payload: CustomFieldCreate,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    key = validate_field_definition_key(payload.key)
    if payload.type in ("select", "multiselect"):
        if not isinstance(payload.options, list) or not payload.options:
            raise ApiError(
                "INVALID_FIELD_OPTIONS", "select fields require a non-empty options list", 422
            )
    field = CrmCustomField(
        entity=payload.entity,
        key=key,
        label=payload.label.strip(),
        type=payload.type,
        options=payload.options,
        required=payload.required,
        sort=payload.sort,
    )
    session.add(field)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError("FIELD_EXISTS", "This entity already has this field key", 409) from exc
    await session.refresh(field)
    await log_activity(
        session,
        admin.id,
        "custom_field",
        field.id,
        "custom_field_created",
        diff_payload(None, slim({"entity": field.entity, "key": field.key})),
    )
    await session.commit()
    return CustomFieldOut.model_validate(field)


@router.patch("/{field_id}", response_model=CustomFieldOut)
async def update_custom_field(
    field_id: uuid.UUID,
    payload: CustomFieldUpdate,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    field = await session.get(CrmCustomField, field_id)
    if field is None:
        raise ApiError("NOT_FOUND", "Custom field not found", 404)
    before = slim({"label": field.label, "required": field.required})
    if payload.label is not None:
        field.label = payload.label.strip()
    if payload.options is not None:
        field.options = payload.options
    if payload.required is not None:
        field.required = payload.required
    if payload.sort is not None:
        field.sort = payload.sort
    await session.commit()
    await session.refresh(field)
    await log_activity(
        session,
        admin.id,
        "custom_field",
        field.id,
        "custom_field_updated",
        diff_payload(before, slim({"label": field.label})),
    )
    await session.commit()
    return CustomFieldOut.model_validate(field)


@router.delete("/{field_id}")
async def delete_custom_field(
    field_id: uuid.UUID,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    field = await session.get(CrmCustomField, field_id)
    if field is None:
        raise ApiError("NOT_FOUND", "Custom field not found", 404)
    await log_activity(
        session,
        admin.id,
        "custom_field",
        field.id,
        "custom_field_deleted",
        diff_payload(slim({"entity": field.entity, "key": field.key}), None),
    )
    await session.delete(field)
    await session.commit()
    return {"ok": True}
