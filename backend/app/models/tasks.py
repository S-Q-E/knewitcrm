from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

TASK_TYPE_CALL = "call"
TASK_TYPE_MEETING = "meeting"
TASK_TYPE_MESSAGE = "message"
TASK_TYPE_OTHER = "other"
VALID_TASK_TYPES = (TASK_TYPE_CALL, TASK_TYPE_MEETING, TASK_TYPE_MESSAGE, TASK_TYPE_OTHER)


class CrmTask(Base):
    """Manager follow-up task, optionally attached to a deal and/or a contact."""

    __tablename__ = "crm_tasks"
    __table_args__ = (
        CheckConstraint(
            "type IN ('call', 'meeting', 'message', 'other')", name="ck_crm_tasks_type"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_deals.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_contacts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False, server_default=TASK_TYPE_OTHER)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
