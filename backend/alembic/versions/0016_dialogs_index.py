"""Index the dialog list ordering (step 9C)."""

from __future__ import annotations

from alembic import op

revision = "0016_dialogs_index"
down_revision = "0015_dialogs_list"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_crm_conversation_state_last_message"
        " ON crm_conversation_state (last_message_at DESC NULLS LAST, whatsapp_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_crm_conversation_state_last_message")
