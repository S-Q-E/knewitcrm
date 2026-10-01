"""Seed the round-robin assignment row so workers can lock it (step 9C)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_round_robin"
down_revision = "0012_outbox_sending"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO crm_settings (key, value) VALUES"
            ' (\'deal_assignment\', \'{"mode": "unassigned", "last_index": -1}\')'
            " ON CONFLICT (key) DO NOTHING"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM crm_settings WHERE key = 'deal_assignment'"))
