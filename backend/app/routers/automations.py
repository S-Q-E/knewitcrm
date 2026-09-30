from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_role, require_user
from ..deps import get_session, pagination
from ..errors import ApiError
from ..models import CrmAutomation
from ..services.activity import diff_payload, log_activity, slim

router = APIRouter(prefix="/api/automations", tags=["automations"])

require_admin = require_role("admin")

TRIGGER_TYPES = ("deal_entered_stage", "no_activity_hours")
ACTION_TYPES = ("create_task", "assign_owner", "add_tag", "notify")


class AutomationAction(BaseModel):
    model_config = {"extra": "allow"}

    type: str = Field(pattern="^(create_task|assign_owner|add_tag|notify)$")


class AutomationOut(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
    trigger_type: str
    trigger_config: dict
    actions: list
    created_at: str

    model_config = {"from_attributes": True}


class AutomationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    is_active: bool = True
    trigger_type: str = Field(pattern="^(deal_entered_stage|no_activity_hours)$")
    trigger_config: dict = Field(default_factory=dict)
    actions: list[AutomationAction] = Field(default_factory=list, max_length=10)


class AutomationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    trigger_type: str | None = Field(
        default=None, pattern="^(deal_entered_stage|no_activity_hours)$"
    )
    trigger_config: dict | None = None
    actions: list[AutomationAction] | None = Field(default=None, max_length=10)


def _out(automation: CrmAutomation) -> AutomationOut:
    return AutomationOut(
        id=automation.id,
        name=automation.name,
        is_active=automation.is_active,
        trigger_type=automation.trigger_type,
        trigger_config=automation.trigger_config or {},
        actions=automation.actions or [],
        created_at=automation.created_at.isoformat(),
    )


@router.get("", response_model=list[AutomationOut])
async def list_automations(
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination),
):
    del user
    rows = (
        await session.execute(
            select(CrmAutomation)
            .order_by(CrmAutomation.created_at.desc())
            .limit(page["limit"])
            .offset(page["offset"])
        )
    ).scalars()
    return [_out(row) for row in rows]


@router.post("", response_model=AutomationOut, status_code=201)
async def create_automation(
    payload: AutomationCreate,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    automation = CrmAutomation(
        name=payload.name.strip(),
        is_active=payload.is_active,
        trigger_type=payload.trigger_type,
        trigger_config=payload.trigger_config,
        actions=[action.model_dump() for action in payload.actions],
    )
    session.add(automation)
    await session.commit()
    await session.refresh(automation)
    await log_activity(
        session,
        admin.id,
        "automation",
        automation.id,
        "automation_created",
        diff_payload(None, slim({"name": automation.name})),
    )
    await session.commit()
    return _out(automation)


@router.patch("/{automation_id}", response_model=AutomationOut)
async def update_automation(
    automation_id: uuid.UUID,
    payload: AutomationUpdate,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    automation = await session.get(CrmAutomation, automation_id)
    if automation is None:
        raise ApiError("NOT_FOUND", "Automation not found", 404)
    if payload.name is not None:
        automation.name = payload.name.strip()
    if payload.is_active is not None:
        automation.is_active = payload.is_active
    if payload.trigger_type is not None:
        automation.trigger_type = payload.trigger_type
    if payload.trigger_config is not None:
        automation.trigger_config = payload.trigger_config
    if payload.actions is not None:
        automation.actions = [action.model_dump() for action in payload.actions]
    await session.commit()
    await session.refresh(automation)
    await log_activity(
        session,
        admin.id,
        "automation",
        automation.id,
        "automation_updated",
        diff_payload(slim({"name": automation.name}), slim({"name": automation.name})),
    )
    await session.commit()
    return _out(automation)


@router.delete("/{automation_id}")
async def delete_automation(
    automation_id: uuid.UUID,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    automation = await session.get(CrmAutomation, automation_id)
    if automation is None:
        raise ApiError("NOT_FOUND", "Automation not found", 404)
    await log_activity(
        session,
        admin.id,
        "automation",
        automation.id,
        "automation_deleted",
        diff_payload(slim({"name": automation.name}), None),
    )
    await session.delete(automation)
    await session.commit()
    return {"ok": True}
