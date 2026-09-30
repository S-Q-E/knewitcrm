from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

DEAL_STATUS_OPEN = "open"
DEAL_STATUS_WON = "won"
DEAL_STATUS_LOST = "lost"
VALID_DEAL_STATUSES = (DEAL_STATUS_OPEN, DEAL_STATUS_WON, DEAL_STATUS_LOST)

HISTORY_SOURCE_MANAGER = "manager"
HISTORY_SOURCE_BOT = "bot"
HISTORY_SOURCE_SYSTEM = "system"
VALID_HISTORY_SOURCES = (HISTORY_SOURCE_MANAGER, HISTORY_SOURCE_BOT, HISTORY_SOURCE_SYSTEM)

DEFAULT_CURRENCY = "KZT"


class CrmDeal(Base):
    """CRM deal. One bot lead maps to one managed deal by default (D2)."""

    __tablename__ = "crm_deals"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'won', 'lost')", name="ck_crm_deals_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crm_pipelines.id"), nullable=False, index=True
    )
    stage_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crm_stages.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=DEFAULT_CURRENCY
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(8), nullable=False, server_default=DEAL_STATUS_OPEN)
    lost_reason_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_lost_reasons.id", ondelete="SET NULL"),
        nullable=True,
    )
    trial_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    stage_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=func.false())
    custom: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
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


class CrmDealStageHistory(Base):
    """Recorded deal stage movements (manager, bot, or system)."""

    __tablename__ = "crm_deal_stage_history"
    __table_args__ = (
        CheckConstraint(
            "source IN ('manager', 'bot', 'system')", name="ck_crm_deal_stage_history_source"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_deals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_stage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crm_stages.id", ondelete="SET NULL"), nullable=True
    )
    to_stage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crm_stages.id", ondelete="SET NULL"), nullable=True
    )
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
