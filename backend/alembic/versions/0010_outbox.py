"""Manager outbox queue + quick reply templates (step 9)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_outbox"
down_revision = "0009_sync_snapshot"
branch_labels = None
depends_on = None

_SEED_REPLIES = (
    ("Приветствие", "Здравствуйте, {name}! Чем могу помочь?", 10),
    (
        "Напоминание о пробном",
        "{name}, напоминаем о пробном занятии. Подтвердите, пожалуйста, что придёте!",
        20,
    ),
    (
        "Спасибо за обращение",
        "Спасибо за обращение, {name}! Если появятся вопросы — пишите сюда.",
        30,
    ),
)


def upgrade() -> None:
    op.create_table(
        "crm_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("whatsapp_id", sa.Text(), nullable=False, index=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "sent_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("provider_message_id", sa.Text(), nullable=True),
        sa.Column("knewit_message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'sent', 'failed')", name="ck_crm_outbox_status"),
    )
    op.create_index("ix_crm_outbox_due", "crm_outbox", ["status", "next_attempt_at"])
    op.create_table(
        "crm_quick_replies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False, unique=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
    )
    for title, body, sort in _SEED_REPLIES:
        op.execute(
            sa.text(
                "INSERT INTO crm_quick_replies (id, title, body, sort)"
                " VALUES (gen_random_uuid(), :title, :body, :sort)"
                " ON CONFLICT (title) DO NOTHING"
            ).bindparams(title=title, body=body, sort=sort)
        )


def downgrade() -> None:
    op.drop_table("crm_quick_replies")
    op.drop_index("ix_crm_outbox_due", table_name="crm_outbox")
    op.drop_table("crm_outbox")
