"""Step 16a DB-backed login rate limiting (see D25).

Replaces the former in-memory LoginRateLimiter so the failure budget is
shared across uvicorn workers and container instances. Only crm_* tables
are touched (rules 1-2).
"""

from __future__ import annotations

from alembic import op

revision = "0019_login_attempts"
down_revision = "0018_perf_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS crm_login_attempts ("
        " id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
        " ip VARCHAR(64) NOT NULL,"
        " email VARCHAR(255) NOT NULL,"
        " at TIMESTAMPTZ NOT NULL DEFAULT now()"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_crm_login_attempts_email_at"
        " ON crm_login_attempts (email, at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_crm_login_attempts_ip_email_at"
        " ON crm_login_attempts (ip, email, at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS crm_login_attempts")
