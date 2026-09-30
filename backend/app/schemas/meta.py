from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TagOut(BaseModel):
    id: uuid.UUID
    name: str
    color: str | None

    model_config = {"from_attributes": True}


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    color: str | None = Field(default=None, max_length=16)


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    color: str | None = Field(default=None, max_length=16)


class TagListOut(BaseModel):
    items: list[TagOut]
    total: int


class TagSetIn(BaseModel):
    tag_ids: list[uuid.UUID] = Field(max_length=50)


class LostReasonOut(BaseModel):
    id: uuid.UUID
    name: str
    sort: int

    model_config = {"from_attributes": True}


class LostReasonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    sort: int = 0


class LostReasonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    sort: int | None = None


class LostReasonListOut(BaseModel):
    items: list[LostReasonOut]
    total: int


class CustomFieldOut(BaseModel):
    id: uuid.UUID
    entity: str
    key: str
    label: str
    type: str
    options: Any | None
    required: bool
    sort: int

    model_config = {"from_attributes": True}


class CustomFieldCreate(BaseModel):
    entity: str = Field(pattern="^(contact|deal)$")
    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=255)
    type: str = Field(pattern="^(text|number|date|select|multiselect|bool)$")
    options: Any | None = None
    required: bool = False
    sort: int = 0


class CustomFieldUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=255)
    options: Any | None = None
    required: bool | None = None
    sort: int | None = None


class CustomFieldListOut(BaseModel):
    items: list[CustomFieldOut]
    total: int


class NoteOut(BaseModel):
    id: uuid.UUID
    deal_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    author_id: uuid.UUID | None
    body: str
    pinned: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class NoteCreate(BaseModel):
    deal_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    body: str = Field(min_length=1, max_length=20000)
    pinned: bool = False


class NoteUpdate(BaseModel):
    body: str | None = Field(default=None, min_length=1, max_length=20000)
    pinned: bool | None = None


class NoteListOut(BaseModel):
    items: list[NoteOut]
    total: int
