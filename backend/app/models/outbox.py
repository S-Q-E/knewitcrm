from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

OUTBOX_STATUS_QUEUED = "queued"
OUTBOX_STATUS_SENDING = "sending"
OUTBOX_STATUS_SENT = "sent"
OUTBOX_STATUS_FAILED = "failed"
VALID_OUTBOX_STATUSES = (
    OUTBOX_STATUS_QUEUED,
    OUTBOX_STATUS_SENDING,
    OUTBOX_STATUS_SENT,
    OUTBOX_STATUS_FAILED,
)


class CrmOutbox(Base):
    """Manager outbound message queue (D6). The outbox worker POSTs queued
    rows to the n8n webhook; on success bot_bridge mirrors the text into
    knewit_messages. ``knewit_message_id`` links the exact mirrored row for
    timeline attribution."""

    __tablename__ = "crm_outbox"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'sending', 'sent', 'failed')",
            name="ck_crm_outbox_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    whatsapp_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sent_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=OUTBOX_STATUS_QUEUED
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    knewit_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CrmQuickReply(Base):
    """Manager message templates. ``{name}`` is substituted with the contact name."""

    __tablename__ = "crm_quick_replies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
