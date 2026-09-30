from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SavedViewOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    entity: str
    name: str
    filters: dict[str, Any]
    is_shared: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SavedViewCreate(BaseModel):
    entity: Literal["deal", "contact"] = "deal"
    name: str = Field(min_length=1, max_length=255)
    filters: dict[str, Any] = Field(default_factory=dict)
    is_shared: bool = False


class SavedViewUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    filters: dict[str, Any] | None = None
    is_shared: bool | None = None


class SavedViewListOut(BaseModel):
    items: list[SavedViewOut]
    total: int
