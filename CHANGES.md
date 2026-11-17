# CHANGES — TCS Leasing CRM demo

Work happened in a separate copy (`/home/quanysh/tcs_automation/tcs_demo`,
branch **demo**), not in the original auto-deployed repository. Nothing was
merged or pushed to `main`; the original workspace was not modified.

## Phase 1 — settings and English UI

- `backend/app/config.py`, `.env.example`, `docker-compose.yml`:
  `DEFAULT_TIMEZONE=America/New_York`, `DEFAULT_CURRENCY=USD`.
- Hard-coded KZT/Almaty replaced in `backend/app/services/analytics.py`,
  `schemas/deals.py`, `models/deals.py`, `frontend/src/lib/format.ts`,
  `pages/analytics.tsx`, `pages/settings_profile.tsx` (timezone list:
  New York, Chicago, Denver, Los Angeles, UTC), `api/settings.ts`.
- Full English UI: all `frontend/src/**` (layout, login, deals, dialogs,
  tasks, contacts, contact, deal, bell, analytics, settings, tests).
  Product name «TCS Leasing CRM», permanent «DEMO — fictional data» banner
  (`components/layout.tsx`), `index.html` title/lang.
- Backend user-visible strings translated (`services/timeline.py`,
  `services/analytics.py`, `routers/data_exchange.py`); status constants and
  `services/funnel_seed.py` untouched by design.
- `backend/app/services/normalize.py`: `tg:<chat_id>` no longer treated as a
  phone number; `frontend/src/lib/format.ts` does not render it as a phone.
  Tests updated (`backend/tests/test_contacts_data.py`, `lib/format.test.ts`).
- `backend/tests/test_frontend.py` now expects the new SPA title.

## Pre-Phase-2 commits already in the branch

- Bot tables use the `tcs_*` names everywhere (`backend/app/**`,
  `backend/tests/**`, `scripts/**`, `tests/fixtures/tcs_schema.sql`,
  `docs/**`); `tests/fixtures/knewit_schema.sql` renamed.
- `backend/alembic/versions/0022_sync_contact_fields.py`: bot fields mirrored
  into `crm_contacts.last_bot_*` (migration, crm_* only).
- `RECON.md` — Phase 0 research notes.

## Phase 2 — TCS funnel and demo data

- New `scripts/seed_tcs_demo.py`: guardrails (`DEMO_DB_CONFIRM`,
  refusal on `source='whatsapp'`), idempotent steps, `--reset` that deletes
  only `source='demo'` rows; creates `tcs_units`, the TCS Leasing pipeline
  (single default, 10 stages, 5 lost reasons), `unanswered_after_minutes=2`
  and 30 fictional leads with messages, events and 12 viewings.
- New `backend/tests/test_seed_tcs_demo.py` (protection, idempotency, reset,
  unanswered timing, after-hours share).
- `frontend/src/components/deals/detail.tsx`: bot fields renamed to
  «Unit of interest», «Move-in & budget», «Bedrooms», «Viewing preference»,
  «Objection»; `experience_level` and `lead_data` extras hidden.
- `backend/tests/test_contacts_data.py`: flaky `_wa()` fixed (10 digits).
- `DEMO_SCRIPT.md` stub with the “legacy funnel is not shown” decision.

## Phase 3 — Estimated savings and after-hours KPI

- New `frontend/src/lib/savings.ts` + `savings.test.ts`: pure
  `estimateSavings()` (hours, money, bot seconds, speedup) with null-safe
  response metrics.
- `frontend/src/pages/analytics.tsx`: «Estimated savings» card with three
  editable assumptions (8 min, $25/h, 120 min), `localStorage` persistence in
  `try/catch`, captions «Assumption: replace with TCS numbers» and
  «Estimate based on editable assumptions, not measured results».
- Backend: `after_hours_leads` / `after_hours_share` in
  `services/analytics.py::bot_section`, `schemas/analytics.py`; test coverage
  in `backend/tests/test_analytics.py` (boundaries 08:59/16:59/17:00,
  Saturday, empty period).
- `frontend/src/api/types.ts` regenerated with `npm run gen:api`;
  `api/analytics.ts` hand-written `BotStats` extended; KPI
  «After-hours inquiries captured» added to the Bot card.

## Phase 4 — n8n workflows

- `scripts/build_tcs_workflows.py` — generates all three workflows from the
  original Knewit templates, `docs/tcs/tools-spec.md` and
  `docs/tcs/bot-prompt.md`; `scripts/validate_workflow.py` — structural
  validation (JSON, ids, names, connections).
- Generated:
  - `docs/n8n/tcs-send-message-telegram.workflow.json` (W-A, CRM → Telegram);
  - `workflows/tcs_bot.json` (W-B, bot: Telegram trigger, pause, four tools,
    reply, state/events, agent-error handoff, Sheets node kept disabled);
  - `workflows/tcs_reminders.json` (W-C, 15-minute reminders).
- `docs/tcs/tools-spec.md` (SQL/JS for search_units, get_slots, book_viewing,
  handoff_to_human), `docs/tcs/bot-prompt.md` (verbatim prompt),
  `HUMAN_TODO.md`, `docs/DECISIONS.md` D41–D42, `docs/n8n/README.md`.
- New `backend/tests/test_tcs_workflows.py` (5 static checks).
- `pyproject.toml`: per-file E501 ignore for the builder (embedded JS/SQL).
- `book_viewing` also stores `lead_data.unit` so reminders can render the
  building/unit.

## Phase 5 — demo package

- `README.md` rewritten for TCS Leasing CRM (English UI, USD, Telegram,
  `tcs_*` tables, demo data, deploy and test instructions).
- `DEMO_SCRIPT.md` — full 7-minute scenario with exact lines, recovery table
  and the 30-minute pre-demo checklist.
- `CHANGES.md` — this file.
- `HUMAN_TODO.md` — final list of manual steps.
- `docs/tcs/RAILWAY_DEPLOY.md` — step-by-step Railway deployment.
- `docs/db_schema.md` — `tcs_*` reference updated for the demo
  (`tcs_units`, TCS stages, crm/n8n support tables).
- `docs/tcs/IMPROVEMENT_PLAN.md` — post-demo backlog (failure detection,
  multimodal intake, tickets, RAG, SLA, CI for workflows, legal).

## Not changed

- The original repository and its `main`; no Railway deploy from it.
- No new Python/npm dependencies; no secrets in the repo.
- Bot table names/columns/paths/internal status codes (`ACTIVE`, `ЗАПИСАН`,
  `ДУМАЕТ`, `МЕНЕДЖЕР`, `ОТКАЗ`, `КЛИЕНТ`).
- Legacy funnel «Продажи Knewit» and `services/funnel_seed.py`.
