# Bot DB index recommendations (n8n-owned tables — DO NOT APPLY without the bot owner)

Source: Step 14 EXPLAIN analysis on 100k synthetic `knewit_messages` / 2k leads
(scripts/perf_seed_100k.sql, removed after the analysis). Per hard rule 1 the
CRM never creates indexes (or any DDL) on `knewit_*` tables itself; apply the
statements below consciously on the n8n side (e.g. via the bot project's own
migration) after reviewing write overhead.

Existing bot-side indexes (from tests/fixtures/knewit_schema.sql) already cover
the hot paths and must be kept:
- `idx_messages_whatsapp_created ON knewit_messages (whatsapp_id, created_at)`
  — dialog open, per-dialog outbox mirror lookups, timeline feeds.
- `idx_events_whatsapp ON knewit_events (whatsapp_id)` — timeline event feeds,
  handover (`transferred_to_manager`) lookups.
- `idx_events_type ON knewit_events (event_type)`.
- `idx_leads_status`, `idx_leads_current_stage` — sync worker batch scans.

## Measured on 100k messages / 2k leads (local Postgres 16, warm cache)

| Query (CRM screen) | Plan | Buffers |
|---|---|---|
| Messages by dialog, newest 50 (`/dialogs/{wa}/messages`, timeline) | Bitmap heap scan + in-memory quicksort of ~50 rows | ~59 |
| Events by dialog (`transferred_to_manager` check, `ANY(2000 ids)`) | Bitmap heap scan + sort/unique | small |
| Dialog search `ILIKE %…%` over 2k states (`/dialogs?search=`) | Seq scan + top-N heapsort | ~42 |
| Analytics date aggregates over trailing 30d (~43k rows scanned) | Seq scan + hash aggregate | ~1468 |

HTTP wall time on this dataset: dialogs list ~100ms, search ~100ms, messages
~60ms, board ~250ms, analytics overview ~350ms worst case (full-month period
covering all rows + 1000-row manager roster in dev) / ~120–260ms realistic
(owner filter or 7-day period).

## Recommended statements (bot side only)

```sql
-- Analytics date ranges + retention cleanup currently seq-scan.
CREATE INDEX IF NOT EXISTS idx_messages_created_at
  ON knewit_messages (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_created_at
  ON knewit_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_created_at
  ON knewit_leads (created_at DESC);

-- Optional: skip the small in-memory sort on per-dialog feeds
-- (only if profiling shows it; the composite supersedes
-- idx_messages_whatsapp_created for these queries, keep both or replace
-- after measuring on production distribution).
CREATE INDEX IF NOT EXISTS idx_messages_wa_created_id
  ON knewit_messages (whatsapp_id, created_at DESC, id DESC);

-- Optional: handover/event-type lookups scoped to a dialog.
CREATE INDEX IF NOT EXISTS idx_events_wa_type
  ON knewit_events (whatsapp_id, event_type);
```

## Deliberately NOT recommended

- `pg_trgm` GIN indexes for dialog `ILIKE %…%` search: only if dialogs grow
  past ~1M rows AND the search path is slow; the trigram index belongs on
  `crm_conversation_state.whatsapp_id`, which the CRM *may* create itself in a
  future migration after measuring (no extension is installed today).
- Covering all analytics with a materialized `crm_*` mart: revisit if traffic
  grows ~100x (see D20); direct reads are fast enough today.
- Raising `shared_buffers` / pool sizes: see pool notes in D22; measure first.
