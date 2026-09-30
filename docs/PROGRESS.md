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
## Step 3 — Contacts + deals + kanban [done]
- [x] Migration `0003_domain`: pipelines, stages, contacts, deals, stage history, lost reasons, tags, entity tags, custom fields, conversation state, settings, activity log (+ seed `Продажи Knewit`: 16 stages, 5 lost reasons)
- [x] `services/bot_bridge.py`: `update_bot_stage` (UPDATE lead + `manual_stage_change` event in one txn); sole writer to `knewit_*`
- [x] `workers/sync_worker.py`: lifespan asyncio task (5s, advisory-xact-lock), backfill in batches, bot moves with history, stage_locked -> activity log only, won/lost + closed_at, `last_synced_at` in settings
- [x] 58 tests (bridge, sync, seed idempotency, lifespan worker) + ruff clean + manual run verified
## Step 4 — Bot sync worker + stage locks (D3) [done]
- [x] Implemented together with Step 3 above (single scope in the step brief): backfill, bot-driven moves, stage_locked, won/lost, idempotency
## Step 4b — Domain model REST API [done]
- [x] Brief arrived out of PROGRESS order; covers funnel/contacts/deals/notes/tags/fields/reasons API
- [x] Migration `0004_notes_position`: `crm_notes` + fractional `position NUMERIC(20,10)`
- [x] Pipelines/stages CRUD (admin), reorder, delete-with-recipient; contacts CRUD + ILIKE/phone search + filters + soft/hard delete + restore; deals CRUD + board (grouped sums, per-column cursors) + move (lock/history/bridge) + unlock + bulk (200, atomic)
- [x] Notes/tags/fields/reasons CRUD with role split; custom type validation; `restrict_managers_to_own` scope (404 on violation); activity log on every mutation
- [x] 80 tests + ruff clean + manual Swagger/curl lifecycle verified
## Step 5 — Chat: SSE realtime + outbox + n8n webhook (D4, D6) [todo]
## Step 5b — Frontend scaffold [done]
- [x] Brief arrived out of PROGRESS order; covers the new `frontend/` shell
- [x] Vite + React 18 + TS strict + Tailwind + shadcn-style ui + Query + Router + lucide; API client (cookies, auto CSRF, 401->/login, toasts); openapi-typescript types + `gen:api` script
- [x] amoCRM layout (icon nav, topbar search, bell stub, user menu), /login + stubs, admin-only /settings, light/dark theme, responsive
- [x] Backend serves `frontend/dist` with SPA fallback + cache headers; multi-stage Dockerfile (node:20 -> python:3.12-slim, migrate-on-boot); CI frontend job (typecheck/lint/format/vitest/build)
- [x] tsc/eslint/prettier/vitest/build green; live run verified (SPA, fallback, assets, login, vite proxy)
- [ ] `docker build` not run locally (no daemon) — verify in CI; staging HTTPS login needs Railway access
## Step 6 — Tasks + remaining meta [todo]
- Notes/tags/custom-fields/lost-reasons API done in Step 4b; left: `crm_tasks` table + tasks endpoints
## Step 6b — Kanban «Сделки» [done]
- [x] Brief arrived out of PROGRESS order; covers the /deals page
- [x] Migration `0005_saved_views` + CRUD endpoints (own/shared, admin-only share); `contact_source` filter on deals list+board; `source` writable on contacts
- [x] Board: columns with sums, cards (contact/amount/owner/tags/trial/activity/lock), dnd-kit drag with optimistic update + rollback, per-column cursor loading, inline quick-create modal, note modal, lost-reason modal, won confirm
- [x] List view: sortable table, column toggle (localStorage), row select + bulk bar; filters in URL + saved views UI; loading/empty/error states; keyboard-accessible drag handles
- [x] Playwright E2E (login → drag → reload → persisted → cleanup) green locally + CI e2e job; manual stage check confirms `manual_stage_change` in bot DB
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
- `bot_bridge.insert_outgoing_message` (outbox sender) belongs to Step 5; manager notifications for `МЕНЕДЖЕР`/locked stages belong to Step 9.
- Staging Railway HTTPS login check: needs Railway project access (unavailable locally); Dockerfile + migrate-on-boot CMD are ready for it.
