from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AssignmentMode = Literal["unassigned", "round_robin"]


class SettingsOut(BaseModel):
    restrict_managers_to_own: bool = False
    auto_pause_on_manager: bool = False
    auto_pause_on_manual_reply: bool = True
    analytics_managers_visible: bool = True
    deal_assignment_mode: AssignmentMode = "unassigned"
    unanswered_after_minutes: int = Field(default=10, ge=1, le=1440)


class SettingsUpdate(BaseModel):
    restrict_managers_to_own: bool | None = None
    auto_pause_on_manager: bool | None = None
    auto_pause_on_manual_reply: bool | None = None
    analytics_managers_visible: bool | None = None
    deal_assignment_mode: AssignmentMode | None = None
    unanswered_after_minutes: int | None = Field(default=None, ge=1, le=1440)


class BotStagesOut(BaseModel):
    stages: list[str]
    statuses: list[str]


class FailedOutboxSummary(BaseModel):
    id: uuid.UUID
    whatsapp_id: str
    error: str | None
    attempts: int
    created_at: datetime


class IntegrationsOut(BaseModel):
    bot_db_ok: bool
    bot_db_latency_ms: float | None = None
    bot_db_error: str | None = None
    leads_count: int | None = None
    messages_count: int | None = None
    events_count: int | None = None
    n8n_configured: bool
    n8n_webhook_url: str | None = None
    outbox_queued: int = 0
    outbox_sending: int = 0
    outbox_sent: int = 0
    outbox_failed: int = 0
    last_failed: FailedOutboxSummary | None = None


class QuickReplyCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=4096)
    sort: int = Field(default=0, ge=0, le=100000)


class QuickReplyUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = Field(default=None, min_length=1, max_length=4096)
    sort: int | None = Field(default=None, ge=0, le=100000)


class ActivityItemOut(BaseModel):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_name: str | None
    entity: str
    entity_id: uuid.UUID | None
    action: str
    diff: dict
    created_at: datetime


class ActivityListOut(BaseModel):
    items: list[ActivityItemOut]
    total: int


class SessionOut(BaseModel):
    id: uuid.UUID
    ip: str | None
    user_agent: str | None
    created_at: datetime
    expires_at: datetime
    is_current: bool


class SessionListOut(BaseModel):
    items: list[SessionOut]


class ProfileUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class OutboxJournalItemOut(BaseModel):
    id: uuid.UUID
    whatsapp_id: str
    body: str
    sent_by: uuid.UUID | None
    sent_by_name: str | None
    status: str
    attempts: int
    next_attempt_at: datetime | None
    error: str | None
    provider_message_id: str | None
    created_at: datetime
    sent_at: datetime | None


class OutboxJournalOut(BaseModel):
    items: list[OutboxJournalItemOut]
    total: int
