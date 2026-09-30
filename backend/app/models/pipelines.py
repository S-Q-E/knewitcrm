from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

STAGE_KIND_OPEN = "open"
STAGE_KIND_WON = "won"
STAGE_KIND_LOST = "lost"
VALID_STAGE_KINDS = (STAGE_KIND_OPEN, STAGE_KIND_WON, STAGE_KIND_LOST)

STATUS_CLIENT = "КЛИЕНТ"
STATUS_LOST = "ОТКАЗ"
STATUS_MANAGER = "МЕНЕДЖЕР"


class CrmPipeline(Base):
    """Sales pipeline (kanban board)."""

    __tablename__ = "crm_pipelines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=func.false())
    sort: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class CrmStage(Base):
    """Pipeline stage. bot_stage_key/bot_status_key link to the n8n funnel."""

    __tablename__ = "crm_stages"
    __table_args__ = (
        CheckConstraint("kind IN ('open', 'won', 'lost')", name="ck_crm_stages_kind"),
        UniqueConstraint("pipeline_id", "name", name="uq_crm_stages_pipeline_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_pipelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    color: Mapped[str] = mapped_column(String(16), nullable=False, server_default="#94A3B8")
    sort: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    kind: Mapped[str] = mapped_column(String(8), nullable=False, server_default=STAGE_KIND_OPEN)
    bot_stage_key: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    bot_status_key: Mapped[str | None] = mapped_column(Text, nullable=True)
