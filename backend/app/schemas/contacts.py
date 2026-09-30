from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .meta import TagOut


class ContactOut(BaseModel):
    id: uuid.UUID
    whatsapp_id: str | None
    name: str | None
    phone: str | None
    email: str | None
    source: str | None
    owner_id: uuid.UUID | None
    custom: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    tags: list[TagOut] = []

    model_config = {"from_attributes": True}


class ContactCreate(BaseModel):
    whatsapp_id: str | None = None
    name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=255)
    owner_id: uuid.UUID | None = None
    custom: dict[str, Any] = Field(default_factory=dict)


class ContactUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=255)
    owner_id: uuid.UUID | None = None
    custom: dict[str, Any] | None = None


class ContactListOut(BaseModel):
    items: list[ContactOut]
    total: int
