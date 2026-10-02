"""Analytics calculations (step 12).

All aggregates are computed on the backend with SQL. Reads touch both
crm_* and n8n-owned knewit_* tables; nothing here writes to knewit_*
(rule 1), so no bot_bridge involvement is needed. No index is created
on knewit_* tables; hotspot crm_* columns are indexed by migration
0017_analytics_indexes.

Conventions (see D20):
- Period params are calendar dates (YYYY-MM-DD) interpreted as day
  boundaries in the CRM timezone (settings.default_timezone, default
  Asia/Almaty) and converted to UTC for comparisons. DB stores UTC.
- Funnel is cohort-based: deals created in the period; "reached" counts
  history rows (any time) plus mapped bot events, with the current stage
  as fallback for deals without history.
- First response = first incoming message -> first later outgoing
  message (bot or manager) for the linked whatsapp_id.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser
from ..errors import ApiError

MAX_RANGE_DAYS = 366
TAG_LIMIT = 50
OBJECTION_LIMIT = 10


@dataclass(frozen=True)
class AnalyticsFilters:
    date_from: date
    date_to: date
    start_utc: datetime
    end_utc: datetime
    tz_name: str
    pipeline_id: uuid.UUID
    owner_id: uuid.UUID | None
    granularity: str
    restricted: bool
    user_id: uuid.UUID


def _parse_date(value: str | None, name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ApiError("INVALID_PERIOD", f"{name} must be YYYY-MM-DD", 422) from None


async def resolve_filters(
    session: AsyncSession,
    user: CurrentUser,
    *,
    date_from: str | None,
    date_to: str | None,
    pipeline_id: str | None,
    owner_id: str | None,
    granularity: str,
    tz_name: str,
) -> AnalyticsFilters:
    from ..models import CrmPipeline, CrmUser

    if granularity not in ("day", "week"):
        raise ApiError("INVALID_GRANULARITY", "granularity must be day or week", 422)
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz_name = "UTC"
        tz = ZoneInfo("UTC")

    today = datetime.now(tz).date()
    parsed_from = _parse_date(date_from, "date_from")
    parsed_to = _parse_date(date_to, "date_to")
    resolved_to = parsed_to or today
    resolved_from = parsed_from or (resolved_to - timedelta(days=29))
    if resolved_from > resolved_to:
        raise ApiError("INVALID_PERIOD", "date_from must not be after date_to", 422)
    if (resolved_to - resolved_from).days > MAX_RANGE_DAYS:
        raise ApiError("PERIOD_TOO_LARGE", f"Period is limited to {MAX_RANGE_DAYS} days", 422)

    start_utc = datetime(
        resolved_from.year, resolved_from.month, resolved_from.day, tzinfo=tz
    ).astimezone(UTC)
    end_utc = (
        datetime(resolved_to.year, resolved_to.month, resolved_to.day, tzinfo=tz)
        + timedelta(days=1)
    ).astimezone(UTC)

    pid: uuid.UUID | None = None
    if pipeline_id is not None:
        try:
            pid = uuid.UUID(pipeline_id)
        except ValueError:
            raise ApiError("NOT_FOUND", "Pipeline not found", 404) from None
        if await session.get(CrmPipeline, pid) is None:
            raise ApiError("NOT_FOUND", "Pipeline not found", 404)
    else:
        row = (
            await session.execute(
                text("SELECT id FROM crm_pipelines WHERE is_default ORDER BY sort LIMIT 1")
            )
        ).scalar_one_or_none()
        if row is None:
            row = (
                await session.execute(text("SELECT id FROM crm_pipelines ORDER BY sort LIMIT 1"))
            ).scalar_one_or_none()
        if row is None:
            raise ApiError("NO_PIPELINE", "No pipeline exists yet", 404)
        pid = uuid.UUID(str(row))

    owner: uuid.UUID | None = None
    if owner_id is not None:
        try:
            owner = uuid.UUID(owner_id)
        except ValueError:
            raise ApiError("UNKNOWN_OWNER", "Owner not found", 422) from None
        if await session.get(CrmUser, owner) is None:
            raise ApiError("UNKNOWN_OWNER", "Owner not found", 422)

    restricted = (
        await session.execute(
            text("SELECT value FROM crm_settings WHERE key = 'restrict_managers_to_own'")
        )
    ).scalar_one_or_none() is True
    if restricted and not user.is_admin:
        if owner is not None and owner != user.id:
            # Same hiding rule as the deals endpoints: scoped-out objects read as 404.
            raise ApiError("NOT_FOUND", "Not found", 404)
        owner = user.id

    return AnalyticsFilters(
        date_from=resolved_from,
        date_to=resolved_to,
        start_utc=start_utc,
        end_utc=end_utc,
        tz_name=tz_name,
        pipeline_id=pid,
        owner_id=owner,
        granularity=granularity,
        restricted=restricted and not user.is_admin,
        user_id=user.id,
    )


def _deal_scope(owner_column: str, filters: AnalyticsFilters, user_param: str = "user_id") -> str:
    """SQL fragment limiting crm_deals rows to the visible owner scope."""
    if filters.owner_id is not None:
        return f"AND {owner_column} = :owner_id"
    if filters.restricted:
        return f"AND ({owner_column} = :{user_param} OR {owner_column} IS NULL)"
    return ""


def _contact_scope(
    owner_column: str, filters: AnalyticsFilters, user_param: str = "user_id"
) -> str:
    if filters.owner_id is not None:
        return f"AND {owner_column} = :owner_id"
    if filters.restricted:
        return f"AND ({owner_column} = :{user_param} OR {owner_column} IS NULL)"
    return ""


def _params(filters: AnalyticsFilters) -> dict:
    params: dict = {
        "start": filters.start_utc,
        "end": filters.end_utc,
        "tz": filters.tz_name,
        "pipeline_id": str(filters.pipeline_id),
        "user_id": str(filters.user_id),
    }
    if filters.owner_id is not None:
        params["owner_id"] = str(filters.owner_id)
    return params


async def _stages(session: AsyncSession, filters: AnalyticsFilters) -> list[dict]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id, name, kind, sort, bot_stage_key FROM crm_stages"
                    " WHERE pipeline_id = :pipeline_id ORDER BY sort, name"
                ),
                {"pipeline_id": str(filters.pipeline_id)},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def funnel_section(session: AsyncSession, filters: AnalyticsFilters) -> dict:
    stages = await _stages(session, filters)
    params = _params(filters)
    deals = (
        (
            await session.execute(
                text(
                    "SELECT d.id, d.stage_id, d.status, c.whatsapp_id FROM crm_deals d"
                    " JOIN crm_contacts c ON c.id = d.contact_id AND c.deleted_at IS NULL"
                    " WHERE d.deleted_at IS NULL AND d.pipeline_id = :pipeline_id"
                    " AND d.created_at >= :start AND d.created_at < :end"
                    f" {_deal_scope('d.owner_id', filters)}"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    deal_ids = [str(r["id"]) for r in deals]
    by_deal = {str(r["id"]): r for r in deals}
    history: list[dict] = []
    if deal_ids:
        history = [
            dict(r)
            for r in (
                await session.execute(
                    text(
                        "SELECT deal_id, from_stage_id, to_stage_id, at"
                        " FROM crm_deal_stage_history WHERE deal_id = ANY(:ids)"
                        " ORDER BY at, id"
                    ),
                    {"ids": deal_ids},
                )
            )
            .mappings()
            .all()
        ]
    per_deal_history: dict[str, list[dict]] = {did: [] for did in deal_ids}
    for row in history:
        per_deal_history.setdefault(str(row["deal_id"]), []).append(row)

    # Bot events mapped onto funnel stages via bot_stage_key (ever, for the cohort).
    key_to_stage = {s["bot_stage_key"]: str(s["id"]) for s in stages if s["bot_stage_key"]}
    bot_reached: dict[str, set[str]] = {}
    deal_wa = {did: (row["whatsapp_id"] if row else None) for did, row in by_deal.items()}
    wa_to_deal = {wa: did for did, wa in deal_wa.items() if wa}
    if wa_to_deal and key_to_stage:
        events = (
            (
                await session.execute(
                    text(
                        "SELECT whatsapp_id, to_stage FROM knewit_events"
                        " WHERE whatsapp_id = ANY(:was)"
                    ),
                    {"was": list(wa_to_deal)},
                )
            )
            .mappings()
            .all()
        )
        for event in events:
            stage_id = key_to_stage.get(event["to_stage"])
            did = wa_to_deal.get(event["whatsapp_id"])
            if stage_id and did:
                bot_reached.setdefault(stage_id, set()).add(did)

    reached: dict[str, set[str]] = {str(s["id"]): set() for s in stages}
    for row in history:
        to_stage = str(row["to_stage_id"]) if row["to_stage_id"] is not None else None
        if to_stage in reached:
            reached[to_stage].add(str(row["deal_id"]))
    for stage_id, dids in bot_reached.items():
        if stage_id in reached:
            reached[stage_id] |= dids
    # Fallback for deals without any history row: their current stage counts as reached.
    deals_with_history = {str(row["deal_id"]) for row in history}
    for did, row in by_deal.items():
        if did not in deals_with_history and str(row["stage_id"]) in reached:
            reached[str(row["stage_id"])].add(did)

    # Average time on stage from completed stays only (a later move closes the stay).
    stays: dict[str, list[float]] = {str(s["id"]): [] for s in stages}
    for _did, rows in per_deal_history.items():
        ordered = sorted(rows, key=lambda r: (r["at"], str(r["to_stage_id"] or "")))
        for prev, current in zip(ordered, ordered[1:], strict=False):
            stage_id = str(prev["to_stage_id"]) if prev["to_stage_id"] is not None else None
            if stage_id in stays and current["at"] and prev["at"]:
                stays[stage_id].append((current["at"] - prev["at"]).total_seconds() / 3600)
    current_counts: dict[str, int] = {str(s["id"]): 0 for s in stages}
    for row in deals:
        stage_id = str(row["stage_id"])
        if stage_id in current_counts:
            current_counts[stage_id] += 1

    items = []
    previous_reached: int | None = None
    for stage in stages:
        sid = str(stage["id"])
        count = len(reached[sid])
        conv = (count / previous_reached) if previous_reached else None
        avg = sum(stays[sid]) / len(stays[sid]) if stays[sid] else None
        items.append(
            {
                "stage_id": sid,
                "name": stage["name"],
                "kind": stage["kind"],
                "reached": count,
                "current": current_counts[sid],
                "conversion_from_prev": round(conv, 4) if conv is not None else None,
                "avg_hours_on_stage": round(avg, 2) if avg is not None else None,
                "is_bottleneck": False,
            }
        )
        previous_reached = count

    # Bottleneck = reached open stage with the lowest step conversion.
    candidates = [i for i in items if i["reached"] > 0 and i["conversion_from_prev"] is not None]
    if candidates:
        worst = min(candidates, key=lambda i: (i["conversion_from_prev"] or 0))
        worst["is_bottleneck"] = True
    first_reached = items[0]["reached"] if items else 0
    finished = sum(1 for row in deals if row["status"] == "won")
    overall = (finished / first_reached) if first_reached else None
    return {
        "stages": items,
        "total_entered": first_reached,
        "total_finished": finished,
        "overall_conversion": round(overall, 4) if overall is not None else None,
        "cohort_deals": len(deal_ids),
    }


def _bucket_starts(filters: AnalyticsFilters) -> list[date]:
    days = (filters.date_to - filters.date_from).days + 1
    if filters.granularity == "week":
        starts = []
        cursor = filters.date_from
        while cursor <= filters.date_to:
            starts.append(cursor)
            cursor += timedelta(days=7)
        return starts
    return [filters.date_from + timedelta(days=i) for i in range(days)]


def _bucket_key(day: date, filters: AnalyticsFilters) -> str:
    if filters.granularity == "week":
        delta = (day - filters.date_from).days
        return (filters.date_from + timedelta(days=(delta // 7) * 7)).isoformat()
    return day.isoformat()


async def summary_section(session: AsyncSession, filters: AnalyticsFilters) -> dict:
    params = _params(filters)
    new_leads = (
        await session.execute(
            text(
                "SELECT COUNT(*) FROM knewit_leads l"
                " LEFT JOIN crm_contacts c ON c.whatsapp_id = l.whatsapp_id"
                " AND c.deleted_at IS NULL"
                " WHERE l.created_at >= :start AND l.created_at < :end"
                f" {_contact_scope('c.owner_id', filters)}"
                + (" AND c.id IS NOT NULL" if filters.owner_id is not None else "")
            ),
            params,
        )
    ).scalar() or 0
    trials = (
        await session.execute(
            text(
                "SELECT COUNT(*) FROM crm_deals d"
                " JOIN crm_contacts c ON c.id = d.contact_id AND c.deleted_at IS NULL"
                " WHERE d.deleted_at IS NULL AND d.pipeline_id = :pipeline_id"
                " AND d.trial_at >= :start AND d.trial_at < :end"
                f" {_deal_scope('d.owner_id', filters)}"
            ),
            params,
        )
    ).scalar() or 0
    closed = (
        (
            await session.execute(
                text(
                    "SELECT d.status, COUNT(*), COALESCE(SUM(d.amount), 0) FROM crm_deals d"
                    " JOIN crm_contacts c ON c.id = d.contact_id AND c.deleted_at IS NULL"
                    " WHERE d.deleted_at IS NULL AND d.pipeline_id = :pipeline_id"
                    " AND d.closed_at >= :start AND d.closed_at < :end"
                    f" {_deal_scope('d.owner_id', filters)}"
                    " GROUP BY d.status"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    by_status = {r["status"]: r for r in closed}
    won_count = int(by_status.get("won", {}).get("count", 0) or 0)
    won_sum = float(by_status.get("won", {}).get("coalesce", 0) or 0)
    lost_count = int(by_status.get("lost", {}).get("count", 0) or 0)
    reasons = (
        (
            await session.execute(
                text(
                    "SELECT r.id, r.name, COUNT(*) FROM crm_deals d"
                    " LEFT JOIN crm_lost_reasons r ON r.id = d.lost_reason_id"
                    " JOIN crm_contacts c ON c.id = d.contact_id AND c.deleted_at IS NULL"
                    " WHERE d.deleted_at IS NULL AND d.pipeline_id = :pipeline_id"
                    " AND d.status = 'lost' AND d.closed_at >= :start AND d.closed_at < :end"
                    f" {_deal_scope('d.owner_id', filters)}"
                    " GROUP BY r.id, r.name ORDER BY COUNT(*) DESC"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    dynamics = await dynamics_buckets(session, filters)
    return {
        "new_leads": int(new_leads),
        "trials_booked": int(trials),
        "won_count": won_count,
        "won_sum": round(won_sum, 2),
        "avg_check": round(won_sum / won_count, 2) if won_count else 0,
        "lost_count": lost_count,
        "lost_by_reason": [
            {
                "reason_id": str(r["id"]) if r["id"] is not None else None,
                "reason": r["name"] or "Без причины",
                "count": int(r["count"]),
            }
            for r in reasons
        ],
        "dynamics": dynamics,
    }


async def dynamics_buckets(session: AsyncSession, filters: AnalyticsFilters) -> list[dict]:
    params = _params(filters)
    lead_rows = (
        (
            await session.execute(
                text(
                    "SELECT DATE((l.created_at AT TIME ZONE :tz)) AS d, COUNT(*)"
                    " FROM knewit_leads l"
                    " LEFT JOIN crm_contacts c ON c.whatsapp_id = l.whatsapp_id"
                    " AND c.deleted_at IS NULL"
                    " WHERE l.created_at >= :start AND l.created_at < :end"
                    f" {_contact_scope('c.owner_id', filters)}"
                    + (" AND c.id IS NOT NULL" if filters.owner_id is not None else "")
                    + " GROUP BY 1"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    trial_rows = (
        (
            await session.execute(
                text(
                    "SELECT DATE((d.trial_at AT TIME ZONE :tz)) AS d, COUNT(*) FROM crm_deals d"
                    " JOIN crm_contacts c ON c.id = d.contact_id AND c.deleted_at IS NULL"
                    " WHERE d.deleted_at IS NULL AND d.pipeline_id = :pipeline_id"
                    " AND d.trial_at >= :start AND d.trial_at < :end"
                    f" {_deal_scope('d.owner_id', filters)}"
                    " GROUP BY 1"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    won_rows = (
        (
            await session.execute(
                text(
                    "SELECT DATE((d.closed_at AT TIME ZONE :tz)) AS d, COUNT(*),"
                    " COALESCE(SUM(d.amount), 0) FROM crm_deals d"
                    " JOIN crm_contacts c ON c.id = d.contact_id AND c.deleted_at IS NULL"
                    " WHERE d.deleted_at IS NULL AND d.pipeline_id = :pipeline_id"
                    " AND d.status = 'won' AND d.closed_at >= :start AND d.closed_at < :end"
                    f" {_deal_scope('d.owner_id', filters)}"
                    " GROUP BY 1"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    lost_rows = (
        (
            await session.execute(
                text(
                    "SELECT DATE((d.closed_at AT TIME ZONE :tz)) AS d, COUNT(*) FROM crm_deals d"
                    " JOIN crm_contacts c ON c.id = d.contact_id AND c.deleted_at IS NULL"
                    " WHERE d.deleted_at IS NULL AND d.pipeline_id = :pipeline_id"
                    " AND d.status = 'lost' AND d.closed_at >= :start AND d.closed_at < :end"
                    f" {_deal_scope('d.owner_id', filters)}"
                    " GROUP BY 1"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )

    def fold(rows: list[dict], value=lambda r: int(r["count"])) -> dict[str, int | float]:
        folded: dict[str, int | float] = {}
        for row in rows:
            key = _bucket_key(row["d"], filters)
            folded[key] = folded.get(key, 0) + value(row)  # type: ignore[operator]
        return folded

    leads = fold(lead_rows)
    trials = fold(trial_rows)
    won = fold(won_rows)
    won_sum = fold(won_rows, value=lambda r: float(r["coalesce"] or 0))
    lost = fold(lost_rows)
    return [
        {
            "bucket": start.isoformat(),
            "new_leads": int(leads.get(start.isoformat(), 0)),
            "trials": int(trials.get(start.isoformat(), 0)),
            "won": int(won.get(start.isoformat(), 0)),
            "won_sum": round(float(won_sum.get(start.isoformat(), 0)), 2),
            "lost": int(lost.get(start.isoformat(), 0)),
        }
        for start in _bucket_starts(filters)
    ]


async def managers_section(session: AsyncSession, filters: AnalyticsFilters) -> list[dict]:
    """Per-manager aggregates in a fixed handful of GROUP BY queries.

    The previous per-user loop issued 5+ queries per manager (thousands of
    round trips with a big roster); latency must not depend on roster size.
    """
    users = (
        (
            await session.execute(
                text(
                    "SELECT id, name FROM crm_users WHERE is_active"
                    + (" AND id = :owner_id" if filters.owner_id is not None else "")
                    + " ORDER BY name"
                ),
                _params(filters),
            )
        )
        .mappings()
        .all()
    )
    uids = [str(row["id"]) for row in users]
    if not uids:
        return []
    now = datetime.now(UTC)
    deal_params: dict = {
        "pipeline_id": str(filters.pipeline_id),
        "uids": uids,
        "start": filters.start_utc,
        "end": filters.end_utc,
        "now": now,
    }
    in_work_rows = (
        (
            await session.execute(
                text(
                    "SELECT d.owner_id, COUNT(*) FROM crm_deals d"
                    " JOIN crm_contacts c ON c.id = d.contact_id AND c.deleted_at IS NULL"
                    " WHERE d.deleted_at IS NULL AND d.pipeline_id = :pipeline_id"
                    " AND d.status = 'open' AND d.owner_id = ANY(:uids)"
                    " GROUP BY d.owner_id"
                ),
                deal_params,
            )
        )
        .mappings()
        .all()
    )
    in_work = {str(r["owner_id"]): int(r["count"]) for r in in_work_rows}
    closed_rows = (
        (
            await session.execute(
                text(
                    "SELECT d.owner_id, d.status, COUNT(*), COALESCE(SUM(d.amount), 0)"
                    " FROM crm_deals d"
                    " JOIN crm_contacts c ON c.id = d.contact_id AND c.deleted_at IS NULL"
                    " WHERE d.deleted_at IS NULL AND d.pipeline_id = :pipeline_id"
                    " AND d.owner_id = ANY(:uids)"
                    " AND d.closed_at >= :start AND d.closed_at < :end"
                    " GROUP BY d.owner_id, d.status"
                ),
                deal_params,
            )
        )
        .mappings()
        .all()
    )
    closed: dict[str, dict[str, dict]] = {}
    for r in closed_rows:
        closed.setdefault(str(r["owner_id"]), {})[r["status"]] = r
    done_rows = (
        (
            await session.execute(
                text(
                    "SELECT assignee_id, COUNT(*) FROM crm_tasks"
                    " WHERE assignee_id = ANY(:uids)"
                    " AND done_at >= :start AND done_at < :end"
                    " GROUP BY assignee_id"
                ),
                deal_params,
            )
        )
        .mappings()
        .all()
    )
    tasks_done = {str(r["assignee_id"]): int(r["count"]) for r in done_rows}
    overdue_rows = (
        (
            await session.execute(
                text(
                    "SELECT assignee_id, COUNT(*) FROM crm_tasks"
                    " WHERE assignee_id = ANY(:uids) AND done_at IS NULL"
                    " AND due_at IS NOT NULL AND due_at < :now"
                    " GROUP BY assignee_id"
                ),
                deal_params,
            )
        )
        .mappings()
        .all()
    )
    tasks_overdue = {str(r["assignee_id"]): int(r["count"]) for r in overdue_rows}
    wa_rows = (
        (
            await session.execute(
                text(
                    "SELECT d.owner_id, c.whatsapp_id FROM crm_deals d"
                    " JOIN crm_contacts c ON c.id = d.contact_id AND c.deleted_at IS NULL"
                    " WHERE d.deleted_at IS NULL AND d.pipeline_id = :pipeline_id"
                    " AND d.owner_id = ANY(:uids) AND c.whatsapp_id IS NOT NULL"
                ),
                deal_params,
            )
        )
        .mappings()
        .all()
    )
    owner_was: dict[str, list[str]] = {}
    for r in wa_rows:
        owner_was.setdefault(str(r["owner_id"]), []).append(str(r["whatsapp_id"]))
    first_response = await _avg_first_response_by_owner(session, owner_was)

    items = []
    for row in users:
        uid = str(row["id"])
        by_status = closed.get(uid, {})
        won = int(by_status.get("won", {}).get("count", 0) or 0)
        lost = int(by_status.get("lost", {}).get("count", 0) or 0)
        total_closed = won + lost
        items.append(
            {
                "user_id": uid,
                "name": row["name"],
                "deals_in_work": in_work.get(uid, 0),
                "won": won,
                "lost": lost,
                "conversion": round(won / total_closed, 4) if total_closed else None,
                "won_sum": round(float(by_status.get("won", {}).get("coalesce", 0) or 0), 2),
                "avg_first_response_hours": first_response.get(uid),
                "tasks_done": tasks_done.get(uid, 0),
                "tasks_overdue": tasks_overdue.get(uid, 0),
            }
        )
    return items


async def _avg_first_response_by_owner(
    session: AsyncSession, owner_was: dict[str, list[str]]
) -> dict[str, float | None]:
    """First incoming -> first later outgoing per dialog, averaged per owner."""
    all_was = sorted({wa for was in owner_was.values() for wa in was})
    if not all_was:
        return {}
    rows = (
        (
            await session.execute(
                text(
                    "WITH first_in AS ("
                    " SELECT whatsapp_id, MIN(created_at) AS t FROM knewit_messages"
                    " WHERE whatsapp_id = ANY(:was) AND direction = 'in' GROUP BY 1"
                    ") SELECT f.whatsapp_id,"
                    " EXTRACT(EPOCH FROM (o.t - f.t)) / 3600 AS h FROM first_in f"
                    " JOIN LATERAL (SELECT MIN(created_at) AS t FROM knewit_messages"
                    " WHERE whatsapp_id = f.whatsapp_id AND direction = 'out'"
                    " AND created_at >= f.t) o ON TRUE"
                ),
                {"was": all_was},
            )
        )
        .mappings()
        .all()
    )
    wa_hours = {str(r["whatsapp_id"]): float(r["h"]) for r in rows if r["h"] is not None}
    out: dict[str, float | None] = {}
    for owner, was in owner_was.items():
        hours = [wa_hours[wa] for wa in was if wa in wa_hours]
        out[owner] = round(sum(hours) / len(hours), 2) if hours else None
    return out


async def bot_section(session: AsyncSession, filters: AnalyticsFilters) -> dict:
    params = _params(filters)
    restriction_join = (
        " LEFT JOIN crm_contacts c ON c.whatsapp_id = m.whatsapp_id AND c.deleted_at IS NULL"
        if filters.restricted or filters.owner_id is not None
        else ""
    )
    restriction_where = ""
    if filters.owner_id is not None:
        restriction_where = " AND c.owner_id = :owner_id AND c.id IS NOT NULL"
    elif filters.restricted:
        restriction_where = " AND (c.id IS NULL OR c.owner_id = :user_id OR c.owner_id IS NULL)"
    msg_rows = (
        (
            await session.execute(
                text(
                    "SELECT DATE((m.created_at AT TIME ZONE :tz)) AS d, m.direction,"
                    " COUNT(*), COALESCE(SUM(m.tokens_used), 0) AS tokens,"
                    " COALESCE(SUM(m.response_time_ms), 0) AS rt_sum,"
                    " COUNT(m.response_time_ms) AS rt_n FROM knewit_messages m"
                    f"{restriction_join}"
                    " WHERE m.created_at >= :start AND m.created_at < :end"
                    f"{restriction_where} GROUP BY 1, 2 ORDER BY 1"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    messages_in = 0
    messages_out = 0
    tokens_total = 0
    rt_sum = 0
    rt_n = 0
    tokens_by_day: dict[str, int] = {}
    for r in msg_rows:
        day = r["d"].isoformat()
        count = int(r["count"] or 0)
        tokens_by_day[day] = tokens_by_day.get(day, 0) + int(r["tokens"] or 0)
        tokens_total += int(r["tokens"] or 0)
        if r["direction"] == "in":
            messages_in += count
        else:
            messages_out += count
            rt_sum += int(r["rt_sum"] or 0)
            rt_n += int(r["rt_n"] or 0)
    avg_response = (rt_sum / rt_n) if rt_n else None

    lead_filter = ""
    if filters.owner_id is not None:
        lead_filter = " AND c.owner_id = :owner_id AND c.id IS NOT NULL"
    elif filters.restricted:
        lead_filter = " AND (c.id IS NULL OR c.owner_id = :user_id OR c.owner_id IS NULL)"
    cohort = (
        (
            await session.execute(
                text(
                    "SELECT l.whatsapp_id, l.status FROM knewit_leads l"
                    " LEFT JOIN crm_contacts c ON c.whatsapp_id = l.whatsapp_id"
                    " AND c.deleted_at IS NULL"
                    " WHERE l.created_at >= :start AND l.created_at < :end"
                    f"{lead_filter}"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    total = len(cohort)
    manager_now = sum(1 for r in cohort if r["status"] == "МЕНЕДЖЕР")
    was = [r["whatsapp_id"] for r in cohort]
    transferred: set[str] = set()
    if was:
        transferred = {
            str(r)
            for r in (
                await session.execute(
                    text(
                        "SELECT DISTINCT whatsapp_id FROM knewit_events"
                        " WHERE whatsapp_id = ANY(:was)"
                        " AND event_type = 'transferred_to_manager'"
                    ),
                    {"was": was},
                )
            )
            .scalars()
            .all()
        }
    handed = sum(1 for r in cohort if r["status"] == "МЕНЕДЖЕР" or r["whatsapp_id"] in transferred)
    objections = (
        (
            await session.execute(
                text(
                    "SELECT l.last_objection AS objection, COUNT(*) FROM knewit_leads l"
                    " LEFT JOIN crm_contacts c ON c.whatsapp_id = l.whatsapp_id"
                    " AND c.deleted_at IS NULL"
                    " WHERE l.created_at >= :start AND l.created_at < :end"
                    " AND l.last_objection IS NOT NULL AND l.last_objection <> ''"
                    f"{lead_filter} GROUP BY 1 ORDER BY 2 DESC LIMIT {OBJECTION_LIMIT}"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    abandoned = (
        (
            await session.execute(
                text(
                    "SELECT l.current_stage AS stage, COUNT(*) FROM knewit_leads l"
                    " LEFT JOIN crm_contacts c ON c.whatsapp_id = l.whatsapp_id"
                    " AND c.deleted_at IS NULL"
                    " WHERE l.created_at >= :start AND l.created_at < :end"
                    f"{lead_filter} GROUP BY 1 ORDER BY 2 DESC"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    return {
        "messages_in": messages_in,
        "messages_out": messages_out,
        "avg_response_time_ms": round(float(avg_response), 1) if avg_response is not None else None,
        "tokens_total": tokens_total,
        "tokens_by_day": [
            {"bucket": start.isoformat(), "tokens": tokens_by_day.get(start.isoformat(), 0)}
            for start in _bucket_starts(filters)
        ],
        "handover_count": handed,
        "handover_share": round(handed / total, 4) if total else None,
        "manager_status_now": manager_now,
        "closed_without_manager": total - handed,
        "closed_without_manager_share": round((total - handed) / total, 4) if total else None,
        "top_objections": [
            {"objection": r["objection"], "count": int(r["count"])} for r in objections
        ],
        "abandoned_by_stage": [
            {
                "stage": r["stage"] or "—",
                "count": int(r["count"]),
                "share": round(int(r["count"]) / total, 4) if total else None,
            }
            for r in abandoned
        ],
    }


async def sources_tags_section(session: AsyncSession, filters: AnalyticsFilters) -> dict:
    params = _params(filters)
    sources = (
        (
            await session.execute(
                text(
                    "SELECT COALESCE(NULLIF(c.source, ''), 'unknown') AS source, COUNT(*)"
                    " FROM crm_contacts c WHERE c.deleted_at IS NULL"
                    " AND c.created_at >= :start AND c.created_at < :end"
                    f" {_contact_scope('c.owner_id', filters)}"
                    " GROUP BY 1 ORDER BY 2 DESC"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    source_won = (
        (
            await session.execute(
                text(
                    "SELECT COALESCE(NULLIF(c.source, ''), 'unknown') AS source,"
                    " COUNT(*) FILTER (WHERE d.status = 'won') AS won,"
                    " COALESCE(SUM(d.amount) FILTER (WHERE d.status = 'won'), 0) AS won_sum"
                    " FROM crm_deals d"
                    " JOIN crm_contacts c ON c.id = d.contact_id AND c.deleted_at IS NULL"
                    " WHERE d.deleted_at IS NULL AND d.pipeline_id = :pipeline_id"
                    " AND d.created_at >= :start AND d.created_at < :end"
                    f" {_deal_scope('d.owner_id', filters)}"
                    " GROUP BY 1 ORDER BY 2 DESC"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    won_map = {r["source"]: r for r in source_won}
    tag_rows = (
        (
            await session.execute(
                text(
                    "SELECT t.id, t.name, COUNT(DISTINCT d.id) FROM crm_tags t"
                    " JOIN crm_entity_tags et ON et.tag_id = t.id AND et.entity = 'deal'"
                    " JOIN crm_deals d ON d.id = et.entity_id AND d.deleted_at IS NULL"
                    " JOIN crm_contacts c ON c.id = d.contact_id AND c.deleted_at IS NULL"
                    " WHERE d.pipeline_id = :pipeline_id"
                    " AND d.created_at >= :start AND d.created_at < :end"
                    f" {_deal_scope('d.owner_id', filters)}"
                    f" GROUP BY t.id, t.name ORDER BY COUNT(DISTINCT d.id) DESC LIMIT {TAG_LIMIT}"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    tag_won = (
        (
            await session.execute(
                text(
                    "SELECT t.id, COUNT(*) FILTER (WHERE d.status = 'won') AS won,"
                    " COALESCE(SUM(d.amount) FILTER (WHERE d.status = 'won'), 0) AS won_sum"
                    " FROM crm_tags t"
                    " JOIN crm_entity_tags et ON et.tag_id = t.id AND et.entity = 'deal'"
                    " JOIN crm_deals d ON d.id = et.entity_id AND d.deleted_at IS NULL"
                    " JOIN crm_contacts c ON c.id = d.contact_id AND c.deleted_at IS NULL"
                    " WHERE d.pipeline_id = :pipeline_id"
                    " AND d.closed_at >= :start AND d.closed_at < :end"
                    f" {_deal_scope('d.owner_id', filters)}"
                    " GROUP BY t.id"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    tag_won_map = {str(r["id"]): r for r in tag_won}
    return {
        "sources": [
            {
                "source": r["source"],
                "contacts": int(r["count"]),
                "won": int((won_map.get(r["source"]) or {}).get("won", 0) or 0),
                "won_sum": round(float((won_map.get(r["source"]) or {}).get("won_sum", 0) or 0), 2),
            }
            for r in sources
        ],
        "tags": [
            {
                "tag_id": str(r["id"]),
                "tag": r["name"],
                "deals": int(r["count"]),
                "won": int((tag_won_map.get(str(r["id"])) or {}).get("won", 0) or 0),
                "won_sum": round(
                    float((tag_won_map.get(str(r["id"])) or {}).get("won_sum", 0) or 0), 2
                ),
            }
            for r in tag_rows
        ],
    }


async def overview(factory, filters: AnalyticsFilters) -> dict:
    """Run the five read-only sections concurrently on separate connections.

    Sections share nothing, so wall time is the slowest section instead of
    the sum. Five connections per overview fit the default pool (5 + 5
    overflow); raise DB_POOL_SIZE if many managers open analytics at once.
    """

    async def run(section_fn):
        async with factory() as session:
            return await section_fn(session, filters)

    funnel, summary, managers, bot, sources_tags = await asyncio.gather(
        run(funnel_section),
        run(summary_section),
        run(managers_section),
        run(bot_section),
        run(sources_tags_section),
    )
    return {
        "meta": {
            "date_from": filters.date_from.isoformat(),
            "date_to": filters.date_to.isoformat(),
            "granularity": filters.granularity,
            "pipeline_id": str(filters.pipeline_id),
            "owner_id": str(filters.owner_id) if filters.owner_id else None,
            "currency": "KZT",
            "timezone": filters.tz_name,
        },
        "funnel": funnel,
        "summary": summary,
        "managers": managers,
        "bot": bot,
        "sources": sources_tags["sources"],
        "tags": sources_tags["tags"],
    }
