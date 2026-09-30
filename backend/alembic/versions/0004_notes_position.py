"""Notes table + fractional deal positions for kanban ordering."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_notes_position"
down_revision = "0003_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_notes",
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
            "author_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "deal_id IS NOT NULL OR contact_id IS NOT NULL",
            name="ck_crm_notes_target",
        ),
    )
    op.alter_column(
        "crm_deals",
        "position",
        existing_type=sa.Integer(),
        type_=sa.Numeric(20, 10),
        existing_nullable=False,
        existing_server_default="0",
        postgresql_using="position::numeric(20, 10)",
    )


def downgrade() -> None:
    op.alter_column(
        "crm_deals",
        "position",
        existing_type=sa.Numeric(20, 10),
        type_=sa.Integer(),
        existing_nullable=False,
        existing_server_default="0",
        postgresql_using="position::integer",
    )
    op.drop_table("crm_notes")
