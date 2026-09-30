"""Sync snapshot columns so the worker never clobbers manager edits."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_sync_snapshot"
down_revision = "0008_task_target_optional"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("crm_contacts", sa.Column("last_bot_name", sa.String(255), nullable=True))
    op.add_column(
        "crm_deals",
        sa.Column("last_bot_trial_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfill snapshots from the bot tables so the first new-logic sync can
    # tell "bot unchanged, manager edited" apart from "bot changed".
    # knewit_* tables are n8n-owned and may be absent (fresh local DB):
    # guard with a table-existence check inside a DO block.
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'knewit_leads') THEN "
            "UPDATE crm_contacts c SET last_bot_name = l.name "
            "FROM knewit_leads l "
            "WHERE l.whatsapp_id = c.whatsapp_id "
            "AND c.whatsapp_id IS NOT NULL AND c.last_bot_name IS NULL; "
            "UPDATE crm_deals d SET last_bot_trial_at = l.trial_datetime "
            "FROM knewit_leads l JOIN crm_contacts c ON c.id = d.contact_id "
            "WHERE l.whatsapp_id = c.whatsapp_id "
            "AND d.last_bot_trial_at IS NULL AND l.trial_datetime IS NOT NULL; "
            "END IF; END $$"
        )
    )


def downgrade() -> None:
    op.drop_column("crm_deals", "last_bot_trial_at")
    op.drop_column("crm_contacts", "last_bot_name")
