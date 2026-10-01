from __future__ import annotations

from pydantic import BaseModel


class AnalyticsMeta(BaseModel):
    date_from: str
    date_to: str
    granularity: str
    pipeline_id: str
    owner_id: str | None
    currency: str
    timezone: str


class FunnelStageOut(BaseModel):
    stage_id: str
    name: str
    kind: str
    reached: int
    current: int
    conversion_from_prev: float | None
    avg_hours_on_stage: float | None
    is_bottleneck: bool


class FunnelOut(BaseModel):
    stages: list[FunnelStageOut]
    total_entered: int
    total_finished: int
    overall_conversion: float | None
    cohort_deals: int


class LostReasonSlice(BaseModel):
    reason_id: str | None
    reason: str
    count: int


class DynamicsBucket(BaseModel):
    bucket: str
    new_leads: int
    trials: int
    won: int
    won_sum: float
    lost: int


class SummaryOut(BaseModel):
    new_leads: int
    trials_booked: int
    won_count: int
    won_sum: float
    avg_check: float
    lost_count: int
    lost_by_reason: list[LostReasonSlice]
    dynamics: list[DynamicsBucket]


class ManagerRow(BaseModel):
    user_id: str
    name: str
    deals_in_work: int
    won: int
    lost: int
    conversion: float | None
    won_sum: float
    avg_first_response_hours: float | None
    tasks_done: int
    tasks_overdue: int


class TokensBucket(BaseModel):
    bucket: str
    tokens: int


class ObjectionRow(BaseModel):
    objection: str
    count: int


class AbandonedRow(BaseModel):
    stage: str
    count: int
    share: float | None


class BotOut(BaseModel):
    messages_in: int
    messages_out: int
    avg_response_time_ms: float | None
    tokens_total: int
    tokens_by_day: list[TokensBucket]
    handover_count: int
    handover_share: float | None
    manager_status_now: int
    closed_without_manager: int
    closed_without_manager_share: float | None
    top_objections: list[ObjectionRow]
    abandoned_by_stage: list[AbandonedRow]


class SourceRow(BaseModel):
    source: str
    contacts: int
    won: int
    won_sum: float


class TagRow(BaseModel):
    tag_id: str
    tag: str
    deals: int
    won: int
    won_sum: float


class AnalyticsOverviewOut(BaseModel):
    meta: AnalyticsMeta
    funnel: FunnelOut
    summary: SummaryOut
    managers: list[ManagerRow]
    bot: BotOut
    sources: list[SourceRow]
    tags: list[TagRow]
