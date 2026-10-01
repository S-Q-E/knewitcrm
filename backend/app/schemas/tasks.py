from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TaskType = Literal["call", "meeting", "message", "other"]


class TaskOut(BaseModel):
    id: uuid.UUID
    deal_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    assignee_id: uuid.UUID | None
    created_by: uuid.UUID | None
    type: str
    title: str
    due_at: datetime | None
    done_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    deal_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    assignee_id: uuid.UUID | None = None
    type: TaskType = "other"
    title: str = Field(min_length=1, max_length=255)
    due_at: datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    type: TaskType | None = None
    assignee_id: uuid.UUID | None = None
    due_at: datetime | None = None


class TaskListOut(BaseModel):
    items: list[TaskOut]
    total: int


class TaskBulkIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    due_at: datetime | None = None
    unassign_owner: bool = False


class TaskBulkOut(BaseModel):
    updated: int
