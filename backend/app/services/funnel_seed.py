from __future__ import annotations

import uuid

from sqlalchemy import text

DEFAULT_PIPELINE_NAME = "Продажи Knewit"

# (name, color, kind, bot_stage_key, bot_status_key) in funnel order.
# bot_stage_key values come from docs/db_schema.md (knewit_leads.current_stage).
STAGES: tuple[tuple[str, str, str, str | None, str | None], ...] = (
    ("Новый лид", "#38BDF8", "open", "НОВЫЙ_ЛИД", None),
    ("Выявление потребности", "#818CF8", "open", "ВЫЯВЛЕНИЕ_ПОТРЕБНОСТИ", None),
    ("Квалификация", "#A78BFA", "open", "КВАЛИФИКАЦИЯ", None),
    ("Формирование потребности", "#C084FC", "open", "ФОРМИРОВАНИЕ_ПОТРЕБНОСТИ", None),
    ("Презентация решения", "#E879F9", "open", "ПРЕЗЕНТАЦИЯ_РЕШЕНИЯ", None),
    ("Целевое действие", "#F472B6", "open", "ЦЕЛЕВОЕ_ДЕЙСТВИЕ", None),
    ("Работа с возражениями", "#FB7185", "open", "РАБОТА_С_ВОЗРАЖЕНИЕМ", None),
    ("Запись", "#FBBF24", "open", "ЗАПИСЬ", None),
    ("Подтверждение", "#FDE047", "open", "ПОДТВЕРЖДЕНИЕ", None),
    ("Напоминание", "#A3E635", "open", "НАПОМИНАНИЕ", None),
    ("После пробного", "#34D399", "open", "ПОСЛЕ_ПРОБНОГО", None),
    ("Сомнения после пробного", "#FB923C", "open", "СОМНЕНИЯ_ПОСЛЕ_ПРОБНОГО", None),
    ("Думает (follow-up)", "#94A3B8", "open", "ДУМАЕТ_FOLLOWUP", None),
    ("Продажа", "#22C55E", "open", "ПРОДАЖА", None),
    ("Клиент", "#16A34A", "won", None, "КЛИЕНТ"),
    ("Отказ", "#EF4444", "lost", None, "ОТКАЗ"),
)

LOST_REASONS: tuple[str, ...] = (
    "Дорого",
    "Не подошло время",
    "Выбрал другого",
    "Не отвечает",
    "Другое",
)


def seed_default_funnel(conn) -> uuid.UUID:
    """Insert the default pipeline, stages, and lost reasons if missing.

    Idempotent: existing rows (matched by name) are left untouched.
    Works with any sync SQLAlchemy connection (Alembic migrations, run_sync).
    Returns the default pipeline id.
    """
    pipeline_id = conn.execute(
        text("SELECT id FROM crm_pipelines WHERE name = :name"),
        {"name": DEFAULT_PIPELINE_NAME},
    ).scalar_one_or_none()
    if pipeline_id is None:
        pipeline_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO crm_pipelines (id, name, is_default, sort)"
                " VALUES (:id, :name, TRUE, 0)"
            ),
            {"id": str(pipeline_id), "name": DEFAULT_PIPELINE_NAME},
        )

    for sort, (name, color, kind, stage_key, status_key) in enumerate(STAGES):
        exists = conn.execute(
            text("SELECT id FROM crm_stages" " WHERE pipeline_id = :pipeline_id AND name = :name"),
            {"pipeline_id": str(pipeline_id), "name": name},
        ).scalar_one_or_none()
        if exists is None:
            conn.execute(
                text(
                    "INSERT INTO crm_stages"
                    " (id, pipeline_id, name, color, sort, kind, bot_stage_key, bot_status_key)"
                    " VALUES (:id, :pipeline_id, :name, :color, :sort,"
                    " :kind, :stage_key, :status_key)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "pipeline_id": str(pipeline_id),
                    "name": name,
                    "color": color,
                    "sort": sort,
                    "kind": kind,
                    "stage_key": stage_key,
                    "status_key": status_key,
                },
            )

    for sort, name in enumerate(LOST_REASONS):
        exists = conn.execute(
            text("SELECT id FROM crm_lost_reasons WHERE name = :name"), {"name": name}
        ).scalar_one_or_none()
        if exists is None:
            conn.execute(
                text("INSERT INTO crm_lost_reasons (id, name, sort)" " VALUES (:id, :name, :sort)"),
                {"id": str(uuid.uuid4()), "name": name, "sort": sort},
            )
    return pipeline_id
