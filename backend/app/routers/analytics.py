from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_user
from ..deps import get_session, get_settings
from ..errors import ApiError
from ..schemas.analytics import AnalyticsOverviewOut
from ..services.analytics import overview, resolve_filters
from ..services.export import csv_stream

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# Aggregates are bounded by stages/users/tags (tens to hundreds of rows),
# so no pagination applies here. Drill-down reuses the paginated
# /api/deals and /api/contacts lists with the same filters.

EXPORT_SECTIONS = (
    "funnel",
    "dynamics",
    "managers",
    "objections",
    "abandoned",
    "sources",
    "tags",
    "lost_reasons",
)

EXPORT_FIELDS: dict[str, tuple[str, ...]] = {
    "funnel": (
        "stage_id",
        "name",
        "kind",
        "reached",
        "current",
        "conversion_from_prev",
        "avg_hours_on_stage",
        "is_bottleneck",
    ),
    "dynamics": ("bucket", "new_leads", "trials", "won", "won_sum", "lost"),
    "managers": (
        "user_id",
        "name",
        "deals_in_work",
        "won",
        "lost",
        "conversion",
        "won_sum",
        "avg_first_response_hours",
        "tasks_done",
        "tasks_overdue",
    ),
    "objections": ("objection", "count"),
    "abandoned": ("stage", "count", "share"),
    "sources": ("source", "contacts", "won", "won_sum"),
    "tags": ("tag_id", "tag", "deals", "won", "won_sum"),
    "lost_reasons": ("reason_id", "reason", "count"),
}


async def _ensure_analytics_visible(session: AsyncSession, user: CurrentUser) -> None:
    """Managers see analytics only when the setting allows (default true).

    Admins always pass. Hidden analytics read as 403 (not 404): the
    section exists, it is just disabled for the manager role.
    """
    from sqlalchemy import text

    if user.is_admin:
        return
    value = (
        await session.execute(
            text("SELECT value FROM crm_settings WHERE key = 'analytics_managers_visible'")
        )
    ).scalar_one_or_none()
    if value is False:
        raise ApiError("FORBIDDEN", "Analytics is disabled for managers", 403)


@router.get("/overview", response_model=AnalyticsOverviewOut)
async def analytics_overview(
    request: Request,
    date_from: str | None = Query(default=None, max_length=10),
    date_to: str | None = Query(default=None, max_length=10),
    pipeline_id: str | None = Query(default=None, max_length=36),
    owner_id: str | None = Query(default=None, max_length=36),
    granularity: str = Query(default="day", pattern="^(day|week)$"),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    await _ensure_analytics_visible(session, user)
    settings = get_settings()
    filters = await resolve_filters(
        session,
        user,
        date_from=date_from,
        date_to=date_to,
        pipeline_id=pipeline_id,
        owner_id=owner_id,
        granularity=granularity,
        tz_name=settings.default_timezone,
    )
    return await overview(request.app.state.session_factory, filters)


@router.get("/export")
async def analytics_export(
    request: Request,
    section: str = Query(
        pattern="^(funnel|dynamics|managers|objections|abandoned|sources|tags|lost_reasons)$"
    ),
    date_from: str | None = Query(default=None, max_length=10),
    date_to: str | None = Query(default=None, max_length=10),
    pipeline_id: str | None = Query(default=None, max_length=36),
    owner_id: str | None = Query(default=None, max_length=36),
    granularity: str = Query(default="day", pattern="^(day|week)$"),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    await _ensure_analytics_visible(session, user)
    settings = get_settings()
    filters = await resolve_filters(
        session,
        user,
        date_from=date_from,
        date_to=date_to,
        pipeline_id=pipeline_id,
        owner_id=owner_id,
        granularity=granularity,
        tz_name=settings.default_timezone,
    )
    data = await overview(request.app.state.session_factory, filters)
    if section == "funnel":
        rows = data["funnel"]["stages"]
    elif section == "dynamics":
        rows = data["summary"]["dynamics"]
    elif section == "lost_reasons":
        rows = data["summary"]["lost_by_reason"]
    elif section == "objections":
        rows = data["bot"]["top_objections"]
    elif section == "abandoned":
        rows = data["bot"]["abandoned_by_stage"]
    else:
        rows = data[section]
    return StreamingResponse(
        csv_stream(rows, EXPORT_FIELDS[section]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=analytics_{section}.csv"},
    )
