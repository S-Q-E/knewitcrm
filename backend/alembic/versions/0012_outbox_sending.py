"""Outbox delivery states: queued -> sending -> sent|failed (hotfix 9B)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_outbox_sending"
down_revision = "0011_contacts_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_crm_outbox_status", "crm_outbox", type_="check")
    op.add_column(
        "crm_outbox",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_crm_outbox_status",
        "crm_outbox",
        "status IN ('queued', 'sending', 'sent', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_crm_outbox_status", "crm_outbox", type_="check")
    op.drop_column("crm_outbox", "claimed_at")
    op.create_check_constraint(
        "ck_crm_outbox_status",
        "crm_outbox",
        "status IN ('queued', 'sent', 'failed')",
    )
