"""Tombstone for a lost migration that was applied directly to production.

The production database (Railway) contains revision 0022_sync_contact_fields
in crm_alembic_version, but the migration file itself was never committed and
cannot be recovered (nothing named 0022 exists anywhere in git history). The
current application code does not depend on its effects, so this stub keeps
the chain valid and turns `alembic upgrade head` into a no-op on production.

Do not re-implement real DDL here: production already has whatever the lost
migration created. New migrations must chain from this revision.
"""

from __future__ import annotations

revision = "0022_sync_contact_fields"
down_revision = "0021_sync_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op: the real revision was applied to production before this file
    # existed. See docs/DECISIONS.md.
    pass


def downgrade() -> None:
    pass
