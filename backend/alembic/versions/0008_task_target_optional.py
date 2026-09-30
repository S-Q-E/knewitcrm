"""Allow standalone tasks without a deal/contact link (step 8)."""

from __future__ import annotations

from alembic import op

revision = "0008_task_target_optional"
down_revision = "0007_notifications_automations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_crm_tasks_target", "crm_tasks", type_="check")


def downgrade() -> None:
    # Re-adding the check would fail on standalone rows; normalize them first.
    op.execute("DELETE FROM crm_tasks WHERE deal_id IS NULL AND contact_id IS NULL")
    op.create_check_constraint(
        "ck_crm_tasks_target", "crm_tasks", "deal_id IS NOT NULL OR contact_id IS NOT NULL"
    )
