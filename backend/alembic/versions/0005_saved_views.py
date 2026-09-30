"""Saved filter views (kanban filters, step 6)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_saved_views"
down_revision = "0004_notes_position"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_saved_views",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("entity", sa.String(8), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("filters", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("entity IN ('deal', 'contact')", name="ck_crm_saved_views_entity"),
    )


def downgrade() -> None:
    op.drop_table("crm_saved_views")
