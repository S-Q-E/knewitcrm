"""Step 14 perf indexes on crm_* tables (EXPLAIN-driven, see docs/DB_RECOMMENDATIONS.md).

Only crm_* tables are touched (rules 1-2): the activity journal and the
outbox journal both paginate newest-first, which seq-scans + sorts once the
tables grow. knewit_* findings are recommendations only.
"""

from __future__ import annotations

from alembic import op

revision = "0018_perf_indexes"
down_revision = "0017_analytics_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_crm_activity_log_created_at"
        " ON crm_activity_log (created_at DESC, id DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_crm_outbox_status_created"
        " ON crm_outbox (status, created_at DESC, id DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_crm_outbox_status_created")
    op.execute("DROP INDEX IF EXISTS ix_crm_activity_log_created_at")
