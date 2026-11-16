"""Mirror bot phone/source into contacts without clobbering manager edits."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_sync_contact_fields"
down_revision = "0021_sync_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("crm_contacts", sa.Column("last_bot_phone", sa.String(64), nullable=True))
    op.add_column("crm_contacts", sa.Column("last_bot_source", sa.String(32), nullable=True))
    # The bot tables are n8n-owned and may be absent on a fresh local DB.
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'tcs_leads') THEN "
            "UPDATE crm_contacts c SET last_bot_phone = l.phone,"
            " last_bot_source = l.source "
            "FROM tcs_leads l "
            "WHERE l.whatsapp_id = c.whatsapp_id "
            "AND c.whatsapp_id IS NOT NULL; "
            "END IF; END $$"
        )
    )


def downgrade() -> None:
    op.drop_column("crm_contacts", "last_bot_source")
    op.drop_column("crm_contacts", "last_bot_phone")
