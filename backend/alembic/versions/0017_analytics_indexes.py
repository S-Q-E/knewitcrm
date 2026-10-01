"""Analytics indexes on crm_* tables (step 12).

Only crm_* tables are touched (rule 1/2): no index is created on
knewit_* tables owned by n8n.
"""

from __future__ import annotations

from alembic import op

revision = "0017_analytics_indexes"
down_revision = "0016_dialogs_index"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_crm_deals_created_at", "crm_deals (created_at)"),
    ("ix_crm_deals_closed_at", "crm_deals (closed_at)"),
    ("ix_crm_deals_trial_at", "crm_deals (trial_at)"),
    ("ix_crm_deals_status", "crm_deals (status)"),
    ("ix_crm_deals_pipeline_created", "crm_deals (pipeline_id, created_at)"),
    ("ix_crm_deal_stage_history_deal_at", "crm_deal_stage_history (deal_id, at)"),
    ("ix_crm_deal_stage_history_to_stage", "crm_deal_stage_history (to_stage_id)"),
    ("ix_crm_contacts_created_at", "crm_contacts (created_at)"),
    ("ix_crm_contacts_source", "crm_contacts (source)"),
    ("ix_crm_tasks_done_at", "crm_tasks (done_at)"),
    ("ix_crm_tasks_due_at", "crm_tasks (due_at)"),
    ("ix_crm_entity_tags_entity_target", "crm_entity_tags (entity, entity_id)"),
)


def upgrade() -> None:
    for name, target in INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {target}")


def downgrade() -> None:
    for name, _ in reversed(INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")
