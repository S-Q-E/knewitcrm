from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

StageKind = Literal["open", "won", "lost"]


class StageOut(BaseModel):
    id: uuid.UUID
    pipeline_id: uuid.UUID
    name: str
    color: str
    sort: int
    kind: str
    bot_stage_key: str | None
    bot_status_key: str | None

    model_config = {"from_attributes": True}


class StageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    color: str = Field(default="#94A3B8", max_length=16)
    kind: StageKind = "open"
    bot_stage_key: str | None = None
    bot_status_key: str | None = None


class StageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    color: str | None = Field(default=None, max_length=16)
    kind: StageKind | None = None
    bot_stage_key: str | None = None
    bot_status_key: str | None = None


class PipelineOut(BaseModel):
    id: uuid.UUID
    name: str
    is_default: bool
    sort: int
    stages: list[StageOut] = []

    model_config = {"from_attributes": True}


class PipelineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    is_default: bool = False
    sort: int = 0


class PipelineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_default: bool | None = None
    sort: int | None = None


class StageReorderIn(BaseModel):
    ordered_ids: list[uuid.UUID] = Field(min_length=1)
