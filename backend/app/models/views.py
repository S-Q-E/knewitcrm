from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class CrmSavedView(Base):
    """Saved filter set for an entity (personal or shared)."""

    __tablename__ = "crm_saved_views"
    __table_args__ = (
        CheckConstraint("entity IN ('deal', 'contact')", name="ck_crm_saved_views_entity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    entity: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_shared: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=func.false())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
