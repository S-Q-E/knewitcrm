from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_role, require_user
from ..deps import get_session
from ..errors import ApiError
from ..models import CrmDeal, CrmPipeline, CrmStage
from ..schemas.pipelines import (
    PipelineCreate,
    PipelineOut,
    PipelineUpdate,
    StageCreate,
    StageOut,
    StageReorderIn,
    StageUpdate,
)
from ..services.activity import diff_payload, log_activity, slim
from ..services.deal_flow import _append_position

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])
stages_router = APIRouter(prefix="/api/stages", tags=["stages"])

require_admin = require_role("admin")


async def _pipeline_out(session: AsyncSession, pipeline: CrmPipeline) -> PipelineOut:
    stages = (
        await session.execute(
            select(CrmStage)
            .where(CrmStage.pipeline_id == pipeline.id)
            .order_by(CrmStage.sort, CrmStage.name)
        )
    ).scalars()
    out = PipelineOut.model_validate(pipeline)
    out.stages = [StageOut.model_validate(s) for s in stages]
    return out


@router.get("", response_model=list[PipelineOut])
async def list_pipelines(
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    del user
    rows = (
        await session.execute(select(CrmPipeline).order_by(CrmPipeline.sort, CrmPipeline.name))
    ).scalars()
    return [await _pipeline_out(session, p) for p in rows]


@router.post("", response_model=PipelineOut, status_code=201)
async def create_pipeline(
    payload: PipelineCreate,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    pipeline = CrmPipeline(
        name=payload.name.strip(), is_default=payload.is_default, sort=payload.sort
    )
    if pipeline.is_default:
        await session.execute(CrmPipeline.__table__.update().values(is_default=False))
    session.add(pipeline)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError("PIPELINE_EXISTS", "A pipeline with this name already exists", 409) from exc
    await session.refresh(pipeline)
    await log_activity(
        session,
        admin.id,
        "pipeline",
        pipeline.id,
        "pipeline_created",
        diff_payload(None, slim({"name": pipeline.name})),
    )
    await session.commit()
    return await _pipeline_out(session, pipeline)


@router.patch("/{pipeline_id}", response_model=PipelineOut)
async def update_pipeline(
    pipeline_id: uuid.UUID,
    payload: PipelineUpdate,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    pipeline = await session.get(CrmPipeline, pipeline_id)
    if pipeline is None:
        raise ApiError("NOT_FOUND", "Pipeline not found", 404)
    before = slim({"name": pipeline.name, "sort": pipeline.sort})
    if payload.name is not None:
        pipeline.name = payload.name.strip()
    if payload.sort is not None:
        pipeline.sort = payload.sort
    if payload.is_default is not None:
        if payload.is_default:
            await session.execute(
                CrmPipeline.__table__.update()
                .where(CrmPipeline.id != pipeline.id)
                .values(is_default=False)
            )
        pipeline.is_default = payload.is_default
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError("PIPELINE_EXISTS", "A pipeline with this name already exists", 409) from exc
    await session.refresh(pipeline)
    await log_activity(
        session,
        admin.id,
        "pipeline",
        pipeline.id,
        "pipeline_updated",
        diff_payload(before, slim({"name": pipeline.name, "sort": pipeline.sort})),
    )
    await session.commit()
    return await _pipeline_out(session, pipeline)


@router.delete("/{pipeline_id}")
async def delete_pipeline(
    pipeline_id: uuid.UUID,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    pipeline = await session.get(CrmPipeline, pipeline_id)
    if pipeline is None:
        raise ApiError("NOT_FOUND", "Pipeline not found", 404)
    stage_count = (
        await session.execute(
            select(func.count()).select_from(CrmStage).where(CrmStage.pipeline_id == pipeline.id)
        )
    ).scalar()
    if stage_count:
        raise ApiError(
            "PIPELINE_HAS_STAGES", "Delete or move all stages first", 409, {"stages": stage_count}
        )
    await log_activity(
        session,
        admin.id,
        "pipeline",
        pipeline.id,
        "pipeline_deleted",
        diff_payload(slim({"name": pipeline.name}), None),
    )
    await session.delete(pipeline)
    await session.commit()
    return {"ok": True}


@router.post("/{pipeline_id}/stages", response_model=StageOut, status_code=201)
async def create_stage(
    pipeline_id: uuid.UUID,
    payload: StageCreate,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    pipeline = await session.get(CrmPipeline, pipeline_id)
    if pipeline is None:
        raise ApiError("NOT_FOUND", "Pipeline not found", 404)
    top_sort = (
        await session.execute(
            select(func.max(CrmStage.sort)).where(CrmStage.pipeline_id == pipeline.id)
        )
    ).scalar()
    stage = CrmStage(
        pipeline_id=pipeline.id,
        name=payload.name.strip(),
        color=payload.color,
        sort=(top_sort or 0) + 1,
        kind=payload.kind,
        bot_stage_key=payload.bot_stage_key,
        bot_status_key=payload.bot_status_key,
    )
    session.add(stage)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError("STAGE_EXISTS", "A stage with this name already exists", 409) from exc
    await session.refresh(stage)
    await log_activity(
        session,
        admin.id,
        "stage",
        stage.id,
        "stage_created",
        diff_payload(None, slim({"name": stage.name, "pipeline_id": str(pipeline.id)})),
    )
    await session.commit()
    return StageOut.model_validate(stage)


@router.post("/{pipeline_id}/stages/reorder", response_model=list[StageOut])
async def reorder_stages(
    pipeline_id: uuid.UUID,
    payload: StageReorderIn,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    pipeline = await session.get(CrmPipeline, pipeline_id)
    if pipeline is None:
        raise ApiError("NOT_FOUND", "Pipeline not found", 404)
    existing = (
        (await session.execute(select(CrmStage.id).where(CrmStage.pipeline_id == pipeline.id)))
        .scalars()
        .all()
    )
    if set(existing) != set(payload.ordered_ids):
        raise ApiError(
            "STAGE_MISMATCH",
            "ordered_ids must contain exactly the pipeline stages",
            422,
            {"expected": [str(i) for i in existing]},
        )
    for sort, stage_id in enumerate(payload.ordered_ids):
        stage = await session.get(CrmStage, stage_id)
        assert stage is not None
        stage.sort = sort
    await session.commit()
    await log_activity(
        session,
        admin.id,
        "pipeline",
        pipeline.id,
        "stages_reordered",
        {"ordered_ids": [str(i) for i in payload.ordered_ids]},
    )
    await session.commit()
    rows = (
        await session.execute(
            select(CrmStage).where(CrmStage.pipeline_id == pipeline.id).order_by(CrmStage.sort)
        )
    ).scalars()
    return [StageOut.model_validate(s) for s in rows]


@stages_router.patch("/{stage_id}", response_model=StageOut)
async def update_stage(
    stage_id: uuid.UUID,
    payload: StageUpdate,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    stage = await session.get(CrmStage, stage_id)
    if stage is None:
        raise ApiError("NOT_FOUND", "Stage not found", 404)
    before = slim(
        {
            "name": stage.name,
            "color": stage.color,
            "kind": stage.kind,
            "bot_stage_key": stage.bot_stage_key,
            "bot_status_key": stage.bot_status_key,
        }
    )
    if payload.name is not None:
        stage.name = payload.name.strip()
    if payload.color is not None:
        stage.color = payload.color
    if payload.kind is not None:
        stage.kind = payload.kind
    # Empty string clears the bot link (JSON null would mean "no change" here).
    if payload.bot_stage_key is not None:
        stage.bot_stage_key = payload.bot_stage_key or None
    if payload.bot_status_key is not None:
        stage.bot_status_key = payload.bot_status_key or None
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError("STAGE_EXISTS", "A stage with this name already exists", 409) from exc
    await session.refresh(stage)
    await log_activity(
        session,
        admin.id,
        "stage",
        stage.id,
        "stage_updated",
        diff_payload(before, slim({"name": stage.name, "kind": stage.kind})),
    )
    await session.commit()
    return StageOut.model_validate(stage)


@stages_router.delete("/{stage_id}")
async def delete_stage(
    stage_id: uuid.UUID,
    to_stage_id: uuid.UUID | None = Query(default=None),
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    stage = await session.get(CrmStage, stage_id)
    if stage is None:
        raise ApiError("NOT_FOUND", "Stage not found", 404)
    deal_count = (
        await session.execute(
            select(func.count())
            .select_from(CrmDeal)
            .where(CrmDeal.stage_id == stage.id, CrmDeal.deleted_at.is_(None))
        )
    ).scalar()
    if deal_count:
        if to_stage_id is None:
            raise ApiError(
                "STAGE_HAS_DEALS",
                "Stage has deals; pass to_stage_id to move them",
                409,
                {"deals": deal_count},
            )
        recipient = await session.get(CrmStage, to_stage_id)
        if recipient is None or recipient.pipeline_id != stage.pipeline_id:
            raise ApiError("INVALID_RECIPIENT", "Recipient stage must be in the same pipeline", 422)
        if recipient.id == stage.id:
            raise ApiError("INVALID_RECIPIENT", "Recipient stage must differ", 422)
        deals = (
            await session.execute(
                select(CrmDeal).where(CrmDeal.stage_id == stage.id, CrmDeal.deleted_at.is_(None))
            )
        ).scalars()
        for deal in deals:
            deal.stage_id = recipient.id
            deal.position = await _append_position(session, recipient.id)
    await log_activity(
        session,
        admin.id,
        "stage",
        stage.id,
        "stage_deleted",
        diff_payload(slim({"name": stage.name, "pipeline_id": str(stage.pipeline_id)}), None),
    )
    await session.delete(stage)
    await session.commit()
    return {"ok": True, "moved_deals": deal_count or 0}
