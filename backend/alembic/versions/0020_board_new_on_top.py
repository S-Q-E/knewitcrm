"""Board new-on-top: backfill positions in first open stages (see D39).

One-off reorder of the «Новые лиды» column: the first open stage of every
pipeline (kind='open', minimal sort, tie-break by name) gets
position = ROW_NUMBER() OVER (PARTITION BY stage_id ORDER BY created_at
DESC, id) over live deals. Other stages and deals are untouched.
New cards land on top from now on (min(position)-1 at creation); this
backfill only aligns the existing «Новые лиды» column, working columns
keep their manual order.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_board_new_on_top"
down_revision = "0019_login_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "WITH first_open AS ("
            " SELECT DISTINCT ON (pipeline_id) id AS stage_id, pipeline_id"
            " FROM crm_stages WHERE kind = 'open' ORDER BY pipeline_id, sort, name"
            "), ranked AS ("
            " SELECT d.id,"
            " ROW_NUMBER() OVER ("
            " PARTITION BY d.stage_id ORDER BY d.created_at DESC, d.id"
            " ) AS rn"
            " FROM crm_deals d JOIN first_open f ON f.stage_id = d.stage_id"
            " WHERE d.deleted_at IS NULL"
            ")"
            " UPDATE crm_deals d SET position = r.rn FROM ranked r WHERE d.id = r.id"
        )
    )


def downgrade() -> None:
    # No-op by design: the old positions were arbitrary (creation order at
    # max+1) and were not saved anywhere, so there is nothing faithful to
    # restore; rewriting positions again would only destroy the backfilled
    # order and managers' manual adjustments made after the upgrade.
    pass
