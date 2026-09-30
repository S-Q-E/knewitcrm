from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_user
from ..deps import get_session, pagination
from ..errors import ApiError
from ..models import CrmContact, CrmDeal, CrmTask, CrmUser
from ..schemas.tasks import TaskCreate, TaskListOut, TaskOut, TaskUpdate
from ..services.activity import diff_payload, log_activity, slim
from ..services.visibility import (
    ensure_visible,
    is_visible,
    owner_condition,
    restrict_managers_to_own,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


async def _check_target(
    session: AsyncSession,
    deal_id: uuid.UUID | None,
    contact_id: uuid.UUID | None,
) -> None:
    if deal_id is None and contact_id is None:
        raise ApiError("TASK_TARGET_REQUIRED", "deal_id or contact_id is required", 422)
    if deal_id is not None:
        deal = await session.get(CrmDeal, deal_id)
        if deal is None or deal.deleted_at is not None:
            raise ApiError("UNKNOWN_DEAL", "Deal not found", 422)
    if contact_id is not None:
        contact = await session.get(CrmContact, contact_id)
        if contact is None or contact.deleted_at is not None:
            raise ApiError("UNKNOWN_CONTACT", "Contact not found", 422)


async def _check_assignee(session: AsyncSession, assignee_id: uuid.UUID | None) -> None:
    if assignee_id is not None and await session.get(CrmUser, assignee_id) is None:
        raise ApiError("UNKNOWN_ASSIGNEE", "Assignee not found", 422)


async def _get_visible(session: AsyncSession, task_id: uuid.UUID, user: CurrentUser) -> CrmTask:
    task = await session.get(CrmTask, task_id)
    if task is None:
        raise ApiError("NOT_FOUND", "Task not found", 404)
    restricted = await restrict_managers_to_own(session)
    ensure_visible(is_visible(task.assignee_id, user, restricted))
    return task


@router.get("", response_model=TaskListOut)
async def list_tasks(
    deal_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    assignee_id: uuid.UUID | None = None,
    unassigned: bool = False,
    open_only: bool = False,
    overdue: bool = False,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination),
):
    stmt = select(CrmTask)
    if deal_id is not None:
        stmt = stmt.where(CrmTask.deal_id == deal_id)
    if contact_id is not None:
        stmt = stmt.where(CrmTask.contact_id == contact_id)
    if assignee_id is not None:
        stmt = stmt.where(CrmTask.assignee_id == assignee_id)
    if unassigned:
        stmt = stmt.where(CrmTask.assignee_id.is_(None))
    if open_only:
        stmt = stmt.where(CrmTask.done_at.is_(None))
    if overdue:
        stmt = stmt.where(
            CrmTask.done_at.is_(None),
            CrmTask.due_at.is_not(None),
            CrmTask.due_at < datetime.now(UTC),
        )
    restricted = await restrict_managers_to_own(session)
    scope = owner_condition(CrmTask.assignee_id, user, restricted)
    if scope is not None:
        stmt = stmt.where(scope)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await session.execute(
            stmt.order_by(CrmTask.due_at.asc().nulls_last(), CrmTask.created_at.desc())
            .limit(page["limit"])
            .offset(page["offset"])
        )
    ).scalars()
    return TaskListOut(items=[TaskOut.model_validate(t) for t in rows], total=total)


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(
    payload: TaskCreate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    await _check_target(session, payload.deal_id, payload.contact_id)
    await _check_assignee(session, payload.assignee_id)
    task = CrmTask(
        deal_id=payload.deal_id,
        contact_id=payload.contact_id,
        assignee_id=payload.assignee_id,
        created_by=user.id,
        type=payload.type,
        title=payload.title.strip(),
        due_at=payload.due_at,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    await log_activity(
        session,
        user.id,
        "task",
        task.id,
        "task_created",
        diff_payload(None, slim({"title": task.title})),
    )
    await session.commit()
    return TaskOut.model_validate(task)


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    return TaskOut.model_validate(await _get_visible(session, task_id, user))


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    task = await _get_visible(session, task_id, user)
    before = slim({"title": task.title, "type": task.type})
    if payload.title is not None:
        task.title = payload.title.strip()
    if payload.type is not None:
        task.type = payload.type
    if payload.assignee_id is not None:
        await _check_assignee(session, payload.assignee_id)
        task.assignee_id = payload.assignee_id
    if payload.due_at is not None:
        task.due_at = payload.due_at
    await session.commit()
    await session.refresh(task)
    await log_activity(
        session,
        user.id,
        "task",
        task.id,
        "task_updated",
        diff_payload(before, slim({"title": task.title})),
    )
    await session.commit()
    return TaskOut.model_validate(task)


@router.post("/{task_id}/done", response_model=TaskOut)
async def complete_task(
    task_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    task = await _get_visible(session, task_id, user)
    task.done_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(task)
    await log_activity(session, user.id, "task", task.id, "task_done", {})
    await session.commit()
    return TaskOut.model_validate(task)


@router.post("/{task_id}/undone", response_model=TaskOut)
async def reopen_task(
    task_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    task = await _get_visible(session, task_id, user)
    task.done_at = None
    await session.commit()
    await session.refresh(task)
    await log_activity(session, user.id, "task", task.id, "task_reopened", {})
    await session.commit()
    return TaskOut.model_validate(task)


@router.delete("/{task_id}")
async def delete_task(
    task_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    task = await session.get(CrmTask, task_id)
    if task is None:
        raise ApiError("NOT_FOUND", "Task not found", 404)
    if not user.is_admin and task.created_by != user.id:
        raise ApiError("FORBIDDEN", "Only the author or an admin can delete a task", 403)
    await log_activity(
        session,
        user.id,
        "task",
        task.id,
        "task_deleted",
        diff_payload(slim({"title": task.title}), None),
    )
    await session.delete(task)
    await session.commit()
    return {"ok": True}
