"""Tasks table for manager follow-ups (step 7)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_tasks"
down_revision = "0005_saved_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "deal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_deals.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_contacts.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "assignee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("type", sa.String(16), nullable=False, server_default="other"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "type IN ('call', 'meeting', 'message', 'other')", name="ck_crm_tasks_type"
        ),
        sa.CheckConstraint(
            "deal_id IS NOT NULL OR contact_id IS NOT NULL", name="ck_crm_tasks_target"
        ),
    )


def downgrade() -> None:
    op.drop_table("crm_tasks")
