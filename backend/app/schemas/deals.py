from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .meta import TagOut

DealStatus = Literal["open", "won", "lost"]


class DealOut(BaseModel):
    id: uuid.UUID
    contact_id: uuid.UUID
    pipeline_id: uuid.UUID
    stage_id: uuid.UUID
    title: str
    amount: float | None
    currency: str
    owner_id: uuid.UUID | None
    status: str
    lost_reason_id: uuid.UUID | None
    trial_at: datetime | None
    closed_at: datetime | None
    position: float
    stage_locked: bool
    custom: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    tags: list[TagOut] = []

    model_config = {"from_attributes": True}


class DealCreate(BaseModel):
    contact_id: uuid.UUID
    pipeline_id: uuid.UUID
    stage_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    amount: float | None = Field(default=None, ge=0)
    currency: str = Field(default="KZT", min_length=3, max_length=3)
    owner_id: uuid.UUID | None = None
    trial_at: datetime | None = None
    custom: dict[str, Any] = Field(default_factory=dict)


class DealUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    owner_id: uuid.UUID | None = None
    trial_at: datetime | None = None
    status: DealStatus | None = None
    lost_reason_id: uuid.UUID | None = None
    custom: dict[str, Any] | None = None


class DealListOut(BaseModel):
    items: list[DealOut]
    total: int


class DealMoveIn(BaseModel):
    stage_id: uuid.UUID
    position: float | None = None
    lost_reason_id: uuid.UUID | None = None


class BoardColumnOut(BaseModel):
    stage_id: uuid.UUID
    name: str
    kind: str
    total: int
    amount_total: float
    items: list[DealOut]
    next_cursor: str | None = None


class BoardOut(BaseModel):
    pipeline_id: uuid.UUID
    columns: list[BoardColumnOut]


class BulkDealsIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    set_owner_id: uuid.UUID | None = None
    set_stage_id: uuid.UUID | None = None
    set_position: float | None = None
    add_tag_id: uuid.UUID | None = None
    close_lost_reason_id: uuid.UUID | None = None


class BulkDealsOut(BaseModel):
    updated: int


class TimelineItemOut(BaseModel):
    key: str
    kind: str
    at: datetime
    data: dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class TimelineOut(BaseModel):
    items: list[TimelineItemOut]
    next_cursor: str | None = None
