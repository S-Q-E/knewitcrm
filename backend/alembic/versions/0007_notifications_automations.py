"""Notifications and automations tables (step 8)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_notifications_automations"
down_revision = "0006_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_crm_notifications_user_read", "crm_notifications", ["user_id", "read_at"])
    op.create_table(
        "crm_automations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("trigger_config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("actions", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "trigger_type IN ('deal_entered_stage', 'no_activity_hours')",
            name="ck_crm_automations_trigger",
        ),
    )


def downgrade() -> None:
    op.drop_table("crm_automations")
    op.drop_index("ix_crm_notifications_user_read", table_name="crm_notifications")
    op.drop_table("crm_notifications")
