# DB schema (knewit_*)

> Source: reconstructed from `backend/main.py` queries + `frontend/app.js` constants.
> Pending live dump: run `DATABASE_URL=... python scripts/dump_schema.py` against the real n8n database to overwrite this file with actual catalog data.
> CRM never migrates these tables (owned by n8n, read-only except via `bot_bridge.py`).

Tables found: knewit_leads, knewit_messages, knewit_events, knewit_followups

## knewit_leads

| column | type | nullable | default |
|---|---|---|---|
| whatsapp_id | text | NO |  |
| name | text | YES |  |
| current_stage | text | YES |  |
| previous_stage | text | YES |  |
| status | text | NO | 'ACTIVE' |
| direction | text | YES |  |
| goal | text | YES |  |
| experience_level | text | YES |  |
| preferred_format | text | YES |  |
| preferred_time | text | YES |  |
| trial_datetime | timestamptz | YES |  |
| last_objection | text | YES |  |
| created_at | timestamptz | NO | now() |
| updated_at | timestamptz | NO | now() |
| last_message_at | timestamptz | YES |  |
| confidence_last | double precision | YES |  |

PK: whatsapp_id

FKs: (none)

Indexes (inferred, see `tests/fixtures/knewit_schema.sql`):
- idx_leads_status: CREATE INDEX ON knewit_leads (status)
- idx_leads_current_stage: CREATE INDEX ON knewit_leads (current_stage)

## knewit_messages

| column | type | nullable | default |
|---|---|---|---|
| id | bigint | NO | nextval |
| whatsapp_id | text | NO |  |
| direction | text | NO | 'in' |
| message_type | text | NO | 'chat' |
| content | text | YES |  |
| stage_at_moment | text | YES |  |
| tokens_used | integer | YES |  |
| response_time_ms | integer | YES |  |
| created_at | timestamptz | NO | now() |

PK: id

FKs:
- whatsapp_id -> knewit_leads.whatsapp_id

Indexes:
- idx_messages_whatsapp_created: (whatsapp_id, created_at)

## knewit_events

| column | type | nullable | default |
|---|---|---|---|
| id | bigint | NO | nextval |
| whatsapp_id | text | NO |  |
| event_type | text | NO |  |
| from_stage | text | YES |  |
| to_stage | text | YES |  |
| payload | jsonb | NO | '{}' |
| created_at | timestamptz | NO | now() |

PK: id

FKs:
- whatsapp_id -> knewit_leads.whatsapp_id

Indexes:
- idx_events_whatsapp: (whatsapp_id)
- idx_events_type: (event_type)

## knewit_followups

| column | type | nullable | default |
|---|---|---|---|
| id | bigint | NO | nextval |
| whatsapp_id | text | NO |  |
| run_at | timestamptz | YES |  |
| status | text | NO | 'queued' |
| payload | jsonb | NO | '{}' |
| created_at | timestamptz | NO | now() |

PK: id

FKs:
- whatsapp_id -> knewit_leads.whatsapp_id

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
