from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BulkContactsIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    set_owner_id: uuid.UUID | None = None
    add_tag_id: uuid.UUID | None = None
    delete: bool = False


class BulkContactsOut(BaseModel):
    updated: int


class MergeContactsIn(BaseModel):
    winner_id: uuid.UUID
    loser_id: uuid.UUID


class DuplicateGroupOut(BaseModel):
    key: str
    kind: str
    value: str
    contact_ids: list[uuid.UUID]


class DuplicateListOut(BaseModel):
    groups: list[DuplicateGroupOut]
    total: int


class ContactTimelineItemOut(BaseModel):
    key: str
    kind: str
    at: datetime
    data: dict[str, Any] = {}


class ContactTimelineOut(BaseModel):
    items: list[ContactTimelineItemOut]
    next_cursor: str | None = None


class ImportPreviewOut(BaseModel):
    header: list[str]
    total: int
    valid: int
    invalid: int
    preview: list[dict[str, Any]]
    errors: list[dict[str, Any]]


class ImportJobOut(BaseModel):
    id: uuid.UUID
    entity: str
    status: str
    total: int
    ok_count: int
    error_count: int
    errors: list[dict[str, Any]] = []
    created_at: datetime
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}


class TrashItemOut(BaseModel):
    kind: str
    id: uuid.UUID
    name: str | None = None
    deleted_at: datetime | None = None


class TrashListOut(BaseModel):
    items: list[TrashItemOut]
    total: int
