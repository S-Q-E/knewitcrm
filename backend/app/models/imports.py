from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

IMPORT_STATUS_QUEUED = "queued"
IMPORT_STATUS_RUNNING = "running"
IMPORT_STATUS_DONE = "done"
IMPORT_STATUS_FAILED = "failed"
VALID_IMPORT_STATUSES = (
    IMPORT_STATUS_QUEUED,
    IMPORT_STATUS_RUNNING,
    IMPORT_STATUS_DONE,
    IMPORT_STATUS_FAILED,
)


class CrmImport(Base):
    """Background CSV import job with per-row error report."""

    __tablename__ = "crm_imports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name="ck_crm_imports_status",
        ),
        CheckConstraint("entity IN ('contact', 'deal')", name="ck_crm_imports_entity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ok_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    mapping: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    errors: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
