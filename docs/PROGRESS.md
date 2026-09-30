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
## Step 2 — Auth with sessions + roles, remove Basic Auth [done]
- [x] Migration `0002_auth`: `crm_users`, `crm_sessions` (argon2 hashes, sha256 session tokens, CSRF binding, 14-day TTL with sliding renewal)
- [x] `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/auth/change-password`; CSRF double-submit for unsafe methods (login exempt)
- [x] `GET/POST/PATCH /api/users` (+ `GET` one): admin full CRUD with pagination, manager lite list (`id`, `name`); deactivation revokes sessions; last-admin guard; password reset
- [x] Bootstrap first admin from `ADMIN_EMAIL`/`ADMIN_PASSWORD` only when zero admins exist
- [x] Login rate limit 5 fails/10min per IP+email -> 429 (in-memory, see D9); failed logins logged without secrets
- [x] `require_user` / `require_role('admin')`; all `/api/*` except health/ready/login require a session; Basic Auth removed
- [x] 47 tests (auth, users, health, legacy) + ruff clean + manual curl scenario verified
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
- Legacy frontend (`frontend-legacy/`) has no session login form; it stays behind the API auth wall until replaced in Step 7.
