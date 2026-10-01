"""Notification dedupe key with a partial unique index (step 9C)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_notify_dedupe"
down_revision = "0013_round_robin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("crm_notifications", sa.Column("dedupe_key", sa.Text(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE crm_notifications SET dedupe_key = payload->>'dedupe_key'"
            " WHERE payload->>'dedupe_key' IS NOT NULL"
        )
    )
    # Pre-existing unread duplicates would violate the new index; keep latest.
    op.execute(
        sa.text(
            "DELETE FROM crm_notifications a USING crm_notifications b"
            " WHERE a.read_at IS NULL AND b.read_at IS NULL"
            " AND a.dedupe_key IS NOT NULL"
            " AND a.user_id = b.user_id AND a.type = b.type"
            " AND a.dedupe_key = b.dedupe_key"
            " AND (a.created_at, a.id) < (b.created_at, b.id)"
        )
    )
    op.create_index(
        "uq_crm_notifications_dedupe",
        "crm_notifications",
        ["user_id", "type", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("read_at IS NULL AND dedupe_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_crm_notifications_dedupe", table_name="crm_notifications")
    op.drop_column("crm_notifications", "dedupe_key")
