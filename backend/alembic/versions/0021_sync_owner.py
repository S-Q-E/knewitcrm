"""Align the responsible manager across deals, contacts and dialogs (see D40).

The deal is the source of truth. For every contact the managed deal is the
most recently updated live one; its non-NULL owner is copied into the contact
and the conversation state. A managed deal without an owner borrows it from
the dialogue first, then from the contact. Only crm_* tables are touched.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_sync_owner"
down_revision = "0020_board_new_on_top"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A. Managed deal has no owner: take the dialog assignee, then the contact owner.
    op.execute(
        sa.text(
            "WITH managed AS ("
            " SELECT DISTINCT ON (d.contact_id) d.id AS deal_id, d.contact_id"
            " FROM crm_deals d"
            " WHERE d.deleted_at IS NULL"
            " ORDER BY d.contact_id, d.updated_at DESC, d.id"
            ")"
            " UPDATE crm_deals d"
            " SET owner_id = COALESCE(s.assigned_to, c.owner_id)"
            " FROM managed m"
            " JOIN crm_contacts c ON c.id = m.contact_id"
            " LEFT JOIN crm_conversation_state s ON s.whatsapp_id = c.whatsapp_id"
            " WHERE d.id = m.deal_id"
            " AND d.owner_id IS NULL"
            " AND COALESCE(s.assigned_to, c.owner_id) IS NOT NULL"
        )
    )
    # B. Deal owner -> contact owner.
    op.execute(
        sa.text(
            "WITH managed AS ("
            " SELECT DISTINCT ON (d.contact_id) d.contact_id, d.owner_id"
            " FROM crm_deals d"
            " WHERE d.deleted_at IS NULL"
            " ORDER BY d.contact_id, d.updated_at DESC, d.id"
            ")"
            " UPDATE crm_contacts c"
            " SET owner_id = m.owner_id"
            " FROM managed m"
            " WHERE m.contact_id = c.id AND m.owner_id IS NOT NULL"
            " AND c.owner_id IS DISTINCT FROM m.owner_id"
        )
    )
    # C. Deal owner -> existing dialog rows only (no new conversation state).
    op.execute(
        sa.text(
            "WITH managed AS ("
            " SELECT DISTINCT ON (d.contact_id) d.contact_id, d.owner_id"
            " FROM crm_deals d"
            " WHERE d.deleted_at IS NULL"
            " ORDER BY d.contact_id, d.updated_at DESC, d.id"
            ")"
            " UPDATE crm_conversation_state s"
            " SET assigned_to = m.owner_id"
            " FROM managed m"
            " JOIN crm_contacts c ON c.id = m.contact_id"
            " WHERE s.whatsapp_id = c.whatsapp_id AND m.owner_id IS NOT NULL"
            " AND s.assigned_to IS DISTINCT FROM m.owner_id"
        )
    )


def downgrade() -> None:
    # No-op by design: the previous values are not stored anywhere, so there
    # is nothing faithful to restore. Re-running the old assignment would
    # also overwrite managers' manual changes made after the upgrade.
    pass
