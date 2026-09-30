"""Domain tables: pipelines, stages, contacts, deals, history, tags, fields, settings."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_domain"
down_revision = "0002_auth"
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.func.now() if not nullable else None,
    )


def upgrade() -> None:
    op.create_table(
        "crm_pipelines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "crm_stages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "pipeline_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_pipelines.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("color", sa.String(16), nullable=False, server_default="#94A3B8"),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("kind", sa.String(8), nullable=False, server_default="open"),
        sa.Column("bot_stage_key", sa.Text(), nullable=True, index=True),
        sa.Column("bot_status_key", sa.Text(), nullable=True),
        sa.CheckConstraint("kind IN ('open', 'won', 'lost')", name="ck_crm_stages_kind"),
        sa.UniqueConstraint("pipeline_id", "name", name="uq_crm_stages_pipeline_name"),
    )
    op.create_table(
        "crm_lost_reasons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "crm_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("whatsapp_id", sa.Text(), nullable=True, unique=True, index=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(64), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("source", sa.String(32), nullable=True, server_default="bot"),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("custom", postgresql.JSONB(), nullable=False, server_default="{}"),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("deleted_at", nullable=True),
    )
    op.create_table(
        "crm_deals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_contacts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "pipeline_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_pipelines.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "stage_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_stages.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KZT"),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("status", sa.String(8), nullable=False, server_default="open"),
        sa.Column(
            "lost_reason_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_lost_reasons.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("trial_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stage_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("custom", postgresql.JSONB(), nullable=False, server_default="{}"),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("deleted_at", nullable=True),
        sa.CheckConstraint("status IN ('open', 'won', 'lost')", name="ck_crm_deals_status"),
    )
    op.create_table(
        "crm_deal_stage_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "deal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_deals.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "from_stage_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_stages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "to_stage_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_stages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "changed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.String(8), nullable=False),
        _ts("at"),
        sa.CheckConstraint(
            "source IN ('manager', 'bot', 'system')",
            name="ck_crm_deal_stage_history_source",
        ),
    )
    op.create_table(
        "crm_tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("color", sa.String(16), nullable=True),
    )
    op.create_table(
        "crm_entity_tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tag_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_tags.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("entity", sa.String(8), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.CheckConstraint("entity IN ('contact', 'deal')", name="ck_crm_entity_tags_entity"),
        sa.UniqueConstraint("tag_id", "entity", "entity_id", name="uq_crm_entity_tags_target"),
    )
    op.create_table(
        "crm_custom_fields",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entity", sa.String(8), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("entity IN ('contact', 'deal')", name="ck_crm_custom_fields_entity"),
        sa.CheckConstraint(
            "type IN ('text', 'number', 'date', 'select', 'multiselect', 'bool')",
            name="ck_crm_custom_fields_type",
        ),
        sa.UniqueConstraint("entity", "key", name="uq_crm_custom_fields_entity_key"),
    )
    op.create_table(
        "crm_conversation_state",
        sa.Column("whatsapp_id", sa.Text(), primary_key=True),
        sa.Column("bot_paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "paused_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "assigned_to",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("unread_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "crm_settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
    )
    op.create_table(
        "crm_activity_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("entity", sa.String(32), nullable=False, index=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("diff", postgresql.JSONB(), nullable=False, server_default="{}"),
        _ts("created_at"),
    )

    from backend.app.services.funnel_seed import seed_default_funnel

    seed_default_funnel(op.get_bind())


def downgrade() -> None:
    op.drop_table("crm_activity_log")
    op.drop_table("crm_settings")
    op.drop_table("crm_conversation_state")
    op.drop_table("crm_custom_fields")
    op.drop_table("crm_entity_tags")
    op.drop_table("crm_tags")
    op.drop_table("crm_deal_stage_history")
    op.drop_table("crm_deals")
    op.drop_table("crm_contacts")
    op.drop_table("crm_lost_reasons")
    op.drop_table("crm_stages")
    op.drop_table("crm_pipelines")
