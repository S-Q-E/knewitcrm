from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ChatMessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=4096)


class OutboxOut(BaseModel):
    id: uuid.UUID
    whatsapp_id: str
    body: str
    sent_by: uuid.UUID | None
    status: str
    attempts: int
    next_attempt_at: datetime | None
    error: str | None
    provider_message_id: str | None
    created_at: datetime
    sent_at: datetime | None

    model_config = {"from_attributes": True}


class QuickReplyOut(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    sort: int

    model_config = {"from_attributes": True}
