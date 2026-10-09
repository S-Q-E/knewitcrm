# DB schema (knewit_*)

> Source: production structure from `schema_dump.sql` (pg_dump, PostgreSQL 16.14, structure only).
> The test replica is `tests/fixtures/knewit_schema.sql`; it mirrors these tables without
> views and without the n8n/bot helper tables.
> CRM never migrates these tables (owned by n8n, written only via `bot_bridge.py`).

Tables used by the CRM: knewit_leads, knewit_messages, knewit_events, knewit_followups.
Other production tables (not used by the CRM): knewit_ai_metrics, knewit_chat_history,
bot_*, chat_status, reminders, Reminderai, n8n_chat_histories and views knewit_*.

**Production has no foreign keys between knewit_* tables.** Rows are matched by
`whatsapp_id` (VARCHAR(50)). Deleting a lead does not delete its messages or events, so
tests and scripts must remove child rows explicitly.

## knewit_leads

PK `id` (integer, sequence). `whatsapp_id` is UNIQUE, not the primary key.
Trigger `update_knewit_leads_updated_at` sets `updated_at = now()` on every UPDATE.

| column | type | nullable | default |
|---|---|---|---|
| id | integer | NO | nextval(knewit_leads_id_seq) |
| whatsapp_id | varchar(50) | NO |  |
| name | varchar(100) | YES |  |
| status | varchar(30) | YES | 'new' |
| current_stage | varchar(50) | YES | 'НОВЫЙ_ЛИД' |
| previous_stage | varchar(50) | YES |  |
| direction | varchar(100) | YES |  |
| goal | varchar(200) | YES |  |
| experience_level | varchar(50) | YES |  |
| preferred_format | varchar(50) | YES |  |
| preferred_time | varchar(50) | YES |  |
| trial_datetime | timestamptz | YES |  |
| last_objection | text | YES |  |
| primary_objection | text | YES |  |
| confidence_last | numeric(3,2) | YES |  |
| reminder_sent | boolean | YES | false |
| lead_data | jsonb | YES | '{}' |
| source | varchar(100) | YES | 'whatsapp' |
| created_at | timestamptz | YES | CURRENT_TIMESTAMP |
| updated_at | timestamptz | YES | CURRENT_TIMESTAMP |
| last_message_at | timestamptz | YES | CURRENT_TIMESTAMP |
| last_interaction_at | timestamptz | YES | CURRENT_TIMESTAMP |
| client_name, phone, target_course, course_format, class_type, skill_level, student_category | varchar | YES |  |

The last group (`client_name` … `student_category`) is not written by the workflow or the CRM
(see architecture §11.4); its origin is unknown.

## knewit_messages

PK `id` bigint (sequence). `direction` is `varchar(3)` with CHECK `in`/`out`. No FK.
Indexes: `(whatsapp_id)`, `(created_at)`. There is **no** composite `(whatsapp_id, created_at)`
index in production (see docs/DB_RECOMMENDATIONS.md, P2-6).

| column | type | nullable | default |
|---|---|---|---|
| id | bigint | NO | sequence |
| whatsapp_id | varchar(50) | NO |  |
| direction | varchar(3) | NO |  |
| message_type | varchar(20) | YES | 'chat' |
| content | text | YES |  |
| stage_at_moment | varchar(50) | YES |  |
| tokens_used | integer | YES |  |
| response_time_ms | integer | YES |  |
| created_at | timestamptz | YES | CURRENT_TIMESTAMP |

## knewit_events

PK `id` bigint (sequence). No FK.

| column | type | nullable | default |
|---|---|---|---|
| id | bigint | NO | sequence |
| whatsapp_id | varchar(50) | NO |  |
| event_type | varchar(40) | NO |  |
| from_stage | varchar(50) | YES |  |
| to_stage | varchar(50) | YES |  |
| payload | jsonb | YES | '{}' |
| created_at | timestamptz | YES | CURRENT_TIMESTAMP |

## knewit_followups

PK `id` bigint (sequence). No FK. Written by the n8n workflow (`Insert Follow-up`); no consumer
is known (architecture §11.1).

| column | type | nullable | default |
|---|---|---|---|
| id | bigint | NO | sequence |
| whatsapp_id | varchar(50) | NO |  |
| kind | varchar(20) | NO | 'THINKING' |
| scheduled_at | timestamptz | NO |  |
| attempt_number | integer | NO | 1 |
| status | varchar(20) | NO | 'PENDING' |
| message | text | YES |  |
| created_at | timestamptz | YES | CURRENT_TIMESTAMP |
| sent_at | timestamptz | YES |  |

## Distinct values

### knewit_leads.current_stage (from `frontend/app.js` STAGE_LABELS)
- НОВЫЙ_ЛИД
- ВЫЯВЛЕНИЕ_ПОТРЕБНОСТИ
- КВАЛИФИКАЦИЯ
- ФОРМИРОВАНИЕ_ПОТРЕБНОСТИ
- ПРЕЗЕНТАЦИЯ_РЕШЕНИЯ
- ЦЕЛЕВОЕ_ДЕЙСТВИЕ
- РАБОТА_С_ВОЗРАЖЕНИЕМ
- ЗАПИСЬ
- ПОДТВЕРЖДЕНИЕ
- НАПОМИНАНИЕ
- ПОСЛЕ_ПРОБНОГО
- СОМНЕНИЯ_ПОСЛЕ_ПРОБНОГО
- ПРОДАЖА
- ДУМАЕТ_FOLLOWUP

### knewit_leads.status (from `backend/main.py` stats + `frontend/app.js` STATUS_MAP)
- ACTIVE
- ЗАПИСАН
- ДУМАЕТ
- МЕНЕДЖЕР
- ОТКАЗ
- КЛИЕНТ

### knewit_events.event_type (from `frontend/app.js` EVENT_ICONS)
- stage_entered
- stage_exited
- objection_raised
- trial_booked
- transferred_to_manager
- followup_sent
- lead_lost
- sale_won
- (code also writes `manual_stage_change`, see D3)
