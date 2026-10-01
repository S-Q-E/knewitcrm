"""Cache last-message summary on conversation state (step 9C)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_dialogs_list"
down_revision = "0014_notify_dedupe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_conversation_state",
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "crm_conversation_state",
        sa.Column("last_message_direction", sa.Text(), nullable=True),
    )
    op.add_column(
        "crm_conversation_state",
        sa.Column("last_message_preview", sa.Text(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE crm_conversation_state s SET"
            " last_message_at = m.created_at,"
            " last_message_direction = m.direction,"
            " last_message_preview = LEFT(m.content, 200)"
            " FROM (SELECT DISTINCT ON (whatsapp_id) whatsapp_id, direction,"
            " content, created_at FROM knewit_messages"
            " ORDER BY whatsapp_id, created_at DESC, id DESC) m"
            " WHERE m.whatsapp_id = s.whatsapp_id"
        )
    )


def downgrade() -> None:
    op.drop_column("crm_conversation_state", "last_message_preview")
    op.drop_column("crm_conversation_state", "last_message_direction")
    op.drop_column("crm_conversation_state", "last_message_at")
