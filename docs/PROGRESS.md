# Progress

## Step 0 — Urgent protection and audit [done]
- [x] Temporary HTTP Basic Auth for all routes except `/api/health` (`CRM_BASIC_USER` / `CRM_BASIC_PASS`, fail fast)
- [x] `scripts/dump_schema.py` (read-only dump of `knewit_*` into `docs/db_schema.md`)
- [x] `docs/DECISIONS.md` (D1–D7) and this `docs/PROGRESS.md`
- [x] `.env.example`
- [x] `docker-compose.yml` + local Postgres 16 + `tests/fixtures/knewit_schema.sql` + seed
- [x] Legacy frontend moved to `frontend-legacy/`

## Step 1 — Backend skeleton (FastAPI + SQLAlchemy + Alembic) [done]
- [x] `backend/app/` (config, db, deps, errors, middleware, logging, routers, models/base, migrations)
- [x] SQLAlchemy 2.0 async engine, lifecycle in app lifespan (`app.state`)
- [x] Alembic async env, `version_table='crm_alembic_version'`, `include_object` allows only `crm_*`
- [x] Baseline migration `0001_baseline` (empty); `upgrade head` creates only the version table
- [x] Legacy endpoints moved to `routers/legacy_bot.py` (same contract, SQLAlchemy `text()`)
- [x] Unified errors `{error:{code,message,details}}`, request-id middleware, JSON logs, `/api/health` + `/api/ready`
- [x] Pytest (25 tests) + ruff + pre-commit + GitHub Actions (lint + tests on push)
- [x] Contract change: missing lead 404 body is now `{error:{code:NOT_FOUND,...}}` (was `{"detail":...}`)
## Step 2 — Auth with sessions + roles, remove Basic Auth [todo]
## Step 3 — Contacts + deals + kanban [todo]
## Step 4 — Bot sync worker + stage locks (D3) [todo]
## Step 5 — Chat: SSE realtime + outbox + n8n webhook (D4, D6) [todo]
## Step 6 — Tasks, notes, tags, custom fields, lost reasons [todo]
## Step 7 — New React frontend, remove frontend-legacy [todo]
## Step 8 — Funnel analytics + reports [todo]
## Step 9 — Notifications + activity log [todo]
## Step 10 — Saved views + search filters [todo]
## Step 11 — Settings (locale, timezone Asia/Almaty, currency KZT) [todo]
## Step 12 — Roles hardening + admin panel [todo]
## Step 13 — Production deploy (Railway, Dockerfile, migrations) [todo]
## Step 14 — Load test + polling/SSE tuning [todo]
## Step 15 — Docs + handover [todo]
## Step 16 — Final audit [todo]

## Deferred
- Live `DATABASE_URL` dump: `docs/db_schema.md` is reconstructed from code; overwrite via `scripts/dump_schema.py` against real n8n DB when available.
