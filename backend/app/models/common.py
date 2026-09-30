from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

ENTITY_CONTACT = "contact"
ENTITY_DEAL = "deal"
VALID_TAG_ENTITIES = (ENTITY_CONTACT, ENTITY_DEAL)
VALID_FIELD_ENTITIES = (ENTITY_CONTACT, ENTITY_DEAL)


class CrmLostReason(Base):
    """Refusal reasons for lost deals."""

    __tablename__ = "crm_lost_reasons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class CrmTag(Base):
    """Shared tags for contacts and deals."""

    __tablename__ = "crm_tags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)


class CrmEntityTag(Base):
    """Tag attached to a contact or a deal."""

    __tablename__ = "crm_entity_tags"
    __table_args__ = (
        CheckConstraint("entity IN ('contact', 'deal')", name="ck_crm_entity_tags_entity"),
        UniqueConstraint("tag_id", "entity", "entity_id", name="uq_crm_entity_tags_target"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_tags.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity: Mapped[str] = mapped_column(String(8), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)


class CrmCustomField(Base):
    """Custom field definition for contacts or deals."""

    __tablename__ = "crm_custom_fields"
    __table_args__ = (
        CheckConstraint("entity IN ('contact', 'deal')", name="ck_crm_custom_fields_entity"),
        CheckConstraint(
            "type IN ('text', 'number', 'date', 'select', 'multiselect', 'bool')",
            name="ck_crm_custom_fields_type",
        ),
        UniqueConstraint("entity", "key", name="uq_crm_custom_fields_entity_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity: Mapped[str] = mapped_column(String(8), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    options: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=func.false())
    sort: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class CrmSetting(Base):
    """Key-value CRM settings (JSONB values)."""

    __tablename__ = "crm_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSONB, nullable=False
    )


class CrmActivityLog(Base):
    """Audit trail for CRM entity changes."""

    __tablename__ = "crm_activity_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    entity: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    diff: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
