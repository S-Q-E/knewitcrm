from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

CONTACT_SOURCE_BOT = "bot"


class CrmContact(Base):
    """CRM contact. Bot leads link via whatsapp_id (D2)."""

    __tablename__ = "crm_contacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    whatsapp_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str | None] = mapped_column(
        String(32), nullable=True, server_default=CONTACT_SOURCE_BOT
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    custom: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Last bot-provided name seen by sync_worker. Used to detect manual
    # manager edits: contact.name is overwritten only when it still matches
    # this snapshot (or is empty).
    last_bot_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CrmConversationState(Base):
    """Per-chat CRM state (pause, assignment, unread). One row per whatsapp_id."""

    __tablename__ = "crm_conversation_state"

    whatsapp_id: Mapped[str] = mapped_column(Text, primary_key=True)
    bot_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=func.false())
    paused_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crm_users.id", ondelete="SET NULL"), nullable=True
    )
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    unread_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_direction: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_message_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
