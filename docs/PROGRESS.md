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
- [x] Login rate limit 5 fails/10min per IP+email + 20 fails/10min per email -> 429 (in-memory, see D9); IP is the last XFF value added by trusted proxies (`TRUSTED_PROXY_HOPS`, default 1); failed logins logged without secrets
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
## Step 5 — Chat: SSE realtime + outbox + n8n webhook [partially done]
- [x] Outbox half done in Step 9 below (queue, worker, webhook, mirror); SSE realtime polling still [todo]
## Step 5b — Frontend scaffold [done]
- [x] Brief arrived out of PROGRESS order; covers the new `frontend/` shell
- [x] Vite + React 18 + TS strict + Tailwind + shadcn-style ui + Query + Router + lucide; API client (cookies, auto CSRF, 401->/login, toasts); openapi-typescript types + `gen:api` script
- [x] amoCRM layout (icon nav, topbar search, bell stub, user menu), /login + stubs, admin-only /settings, light/dark theme, responsive
- [x] Backend serves `frontend/dist` with SPA fallback + cache headers; multi-stage Dockerfile (node:20 -> python:3.12-slim, migrate-on-boot); CI frontend job (typecheck/lint/format/vitest/build)
- [x] tsc/eslint/prettier/vitest/build green; live run verified (SPA, fallback, assets, login, vite proxy)
- [ ] `docker build` not run locally (no daemon) — verify in CI; staging HTTPS login needs Railway access
## Step 6 — Tasks + remaining meta [done]
- Notes/tags/custom-fields/lost-reasons API done in Step 4b; `crm_tasks` table + tasks endpoints done in Step 7 below
## Step 6b — Kanban «Сделки» [done]
- [x] Brief arrived out of PROGRESS order; covers the /deals page
- [x] Migration `0005_saved_views` + CRUD endpoints (own/shared, admin-only share); `contact_source` filter on deals list+board; `source` writable on contacts
- [x] Board: columns with sums, cards (contact/amount/owner/tags/trial/activity/lock), dnd-kit drag with optimistic update + rollback, per-column cursor loading, inline quick-create modal, note modal, lost-reason modal, won confirm
- [x] List view: sortable table, column toggle (localStorage), row select + bulk bar; filters in URL + saved views UI; loading/empty/error states; keyboard-accessible drag handles
- [x] Playwright E2E (login → drag → reload → persisted → cleanup) green locally + CI e2e job; manual stage check confirms `manual_stage_change` in bot DB
## Step 7 — New React frontend, remove frontend-legacy [done]
- [x] Brief arrived out of PROGRESS order; covers deal card + timeline + dialogs
- [x] Migration `0006_tasks` + tasks CRUD (filters, done/undone, author/admin delete)
- [x] `GET /api/deals/{id}/timeline` (6 sources, keyset cursor, type filter); deal drawer + `/deals/:id` page (inline fields, custom inputs, bot-data block, won/lost/unlock, quick task)
- [x] `/dialogs`: list (last message, unread, assignee, pause badge, filters), open dialog with messages, mark-read, assign/pause, send + quick-reply stubs
- [x] Sync worker counts unread from incoming messages; removed `/api/stats`, `/api/funnel`, `frontend-legacy/`
- [x] 90 backend tests + tsc/eslint/vitest green; E2E (card shows messages+events) green; manual timeline/dialogs curl verified
## Step 8 — Funnel analytics + reports [todo]
## Step 8b — Tasks and notifications [done]
- [x] Brief arrived out of PROGRESS order; covers tasks page + notifications + assignment + automations
- [x] Migrations `0007` (notifications, automations) + `0008` (standalone tasks); tasks API gaps (`/complete`, `mine`/date filters, bulk reschedule); notifications list/read/read-all; automations CRUD (admin)
- [x] Workers: 60s notify loop (overdue/due-soon deduped) + automations; sync handover (urgent task + notify, opt-in autopause), locked-stage and unread-transition notifies; round-robin assignment
- [x] Frontend: /tasks (groups, week view, RHF+zod modal, checkbox, bulk links), bell with count + dropdown + deep links
- [x] 99 backend tests + tsc/eslint/vitest green; 3 E2E green; manual handover/task/bell curl verified
## Step 9 — Notifications + activity log [todo]
## Step 9 — Manager messaging via outbox + n8n webhook (D6) [done]
- [x] Brief for this step implements the outbox half of Step 5 (SSE realtime stays [todo]); old "Step 9 — Notifications + activity log" placeholder is superseded (notifications shipped in Step 8b, activity log in Step 4b)
- [x] Migration `0010_outbox`: `crm_outbox` (body/sent_by/status/attempts/next_attempt_at/error/provider_message_id/knewit_message_id/sent_at + due index) + `crm_quick_replies` (unique title, 3 seeded templates)
- [x] `bot_bridge.insert_outgoing_message` (sole `knewit_messages` writer: out/manager row, lead stage stamp, tokens 0, RETURNING id)
- [x] `POST /api/chats/{wa}/messages` (202, EMPTY_BODY/LEAD_NOT_FOUND, auto-pause default true) + outbox list + `/outbox/{id}/retry` + `/bot/pause|resume` (transition-only timeline events) + quick-replies list; `httpx` promoted to production requirements
- [x] `workers/outbox_worker.py`: advisory-locked cycles, claim via SKIP LOCKED, HTTP outside txn, CAS outcome, exp backoff to 5 attempts then failed+notify, `outbox_loop` in lifespan; 12 backend tests (queue/validation/send+mirror/idempotent double-run/retry-then-success/5-fails-notify/pause-resume-timeline/autopause on-off/retry endpoint/listing+templates/mock-server sender incl. rejection paths/manager e2e with timeline author)
- [x] Timeline: manager messages get `author_kind='manager'` + sender name via outbox link (fallback "Менеджер")
- [x] Frontend `/dialogs`: real composer (Enter send / Shift+Enter newline, bot-active warning), pause banner + "Вернуть боту", queued/failed outbox rows with retry, quick-reply chips with {name} substitution, "Менеджер" labels; 2 new vitest files (15 frontend tests green), tsc/eslint/prettier/build green, OpenAPI types regenerated
- [x] 118 backend tests green; manual local run verified (queue 202, worker attempt recorded, autopause, pause/resume, seeded templates)
- [x] Fix (found while setting up): migration `0009_sync_snapshot` backfill used `JOIN ... ON c.id = d.contact_id` referencing the UPDATE target alias — invalid Postgres; rewrote with comma-FROM + WHERE

## Step 9B — Outbox and chats hotfix [done]
- [x] Worker: mirror in SAVEPOINT (`sent` kept, `error='mirror_failed: ...'` + ERROR log), per-row try/except, `queued -> sending -> sent|failed` with `claimed_at` (migration `0012_outbox_sending`), stale `sending` > 2 min reaped to `failed` without retry, auto-retry only on connect-level errors, read-timeout/5xx fail at once with manual retry (UI warns about possible double delivery)
- [x] `/api/chats/*`: `restrict_managers_to_own` via linked contact owner, pause/resume/send 404 when the lead is gone, retry author-or-admin (403)
- [x] SSE: `new_message`/`bot_event` filtered by linked deal visibility (per-connection owner cache)
- [x] Misc: `ruff check --fix` + `ruff format` green, `SECRET_KEY` optional, Dockerfile non-root user + `--proxy-headers` single process, `railway.json` healthcheck `/api/health`, `.env.example` has `N8N_SEND_WEBHOOK_URL`/`N8N_WEBHOOK_SECRET`, board `sum()` cartesian SAWarning fixed via subquery column
- [x] Tests: mirror-failure single-send, parallel cycles single-send, read-timeout no-retry, stale reaper, chats scope (404s), retry authorship (403), SSE foreign-event hiding; `ruff check backend scripts` + `ruff format --check` green; manual local run verified

## Step 10 — Saved views + search filters [todo]
## Step 10 — Realtime via SSE + event bus (D4) [done]
- [x] Brief for this step arrives out of PROGRESS order (same as Step 9 before it); the saved-views/filter step keeps its number above and stays [todo]
- [x] `services/event_bus.py`: process-local fan-out hub (bounded queues, drop-oldest, publishers never block, subscriber stats, test reset)
- [x] `workers/realtime_poller.py`: 2s poll of `knewit_messages`/`knewit_events` by id (in-memory cursors from current maxima at startup), emits `new_message` + `bot_event`; `realtime_loop` wired in lifespan
- [x] `GET /api/stream` (SSE, cookie auth, per-user visibility filter, 15s heartbeat comments, disconnect cleanup)
- [x] Publishers: `notify()` → `notification`; sync bot moves → `deal_moved` (flushed post-commit per batch); deals create/update/move/bulk → `deal_updated`/`deal_moved`; tasks create → `task_created`; chats queue/retry/pause/resume → `outbox_status`/`bot_paused`; outbox worker sent/failed → `outbox_status`
- [x] 11 backend tests in `test_realtime.py` (bus fanout/backpressure/churn, poller once-only, auth, 2-subscriber broadcast, notification owner-only, heartbeat, sync/manager/task publish, visibility matrix); streaming tests boot real uvicorn (httpx ASGI transport cannot stream, see D16)
- [x] Frontend `useEventStream` (layout-mounted): backoff reconnect, 15s polling fallback, per-event invalidations, ping+toast for own incoming, unread tab title; 5 vitest cases; tsc/eslint/prettier/build green
- [x] `scripts/stream_load_test.py`: 50 concurrent streams, all receive the event, server responsive after close — PASSED

## Step 11b — Контакты и данные [done]
- Note: brief numbering collides with the old `Step 11 — Settings` placeholder below; this step keeps the `11b` suffix like earlier out-of-order briefs (4b/5b/6b), settings stays [todo].
- [x] `/contacts`: таблица (сортировка, выбор колонок в localStorage, пагинация, фильтры, сохранённые виды `entity=contact`), быстрый поиск, массовые действия (тег, ответственный, в корзину)
- [x] Карточка `/contacts/:id`: все сделки контакта, общая лента (`messages/events/stages/notes/tasks/activity`), custom-поля, теги, заметки
- [x] Дубликаты (`GET /api/contacts/duplicates`, `POST /api/contacts/merge`): группы по нормализованному телефону/whatsapp/email; экран «Дубликаты» со слиянием сделок/заметок/задач/тегов; `contact_merged` в `crm_activity_log`; источник остаётся мягко удалённым
- [x] Экспорт CSV/XLSX контактов и сделок с учётом фильтров (потоковый CSV с UTF-8 BOM; `openpyxl` для XLSX); импорт CSV контактов (загрузка → маппинг → предпросмотр с ошибками по строкам → фоновая задача `crm_imports` с отчётом)
- [x] Корзина (`GET /api/trash`, admin): просмотр и восстановление мягко удалённых контактов/сделок
- [x] Тесты: `test_contacts_data.py` (нормализация, дубли+слияние, bulk, экспорт csv/xlsx, импорт с ошибками в фоне, корзина, таймлайн) + `contacts.test.ts` (query/mapping/export-url); ruff clean; ручной прогон API локально
- [ ] Frontend tsc/eslint/vitest/build не запускались локально (нет Node); проверить в CI
## Step 11 — Settings (locale, timezone Asia/Almaty, currency KZT) [todo]
## Step 12 — Roles hardening + admin panel [todo]
## Step 13 — Production deploy (Railway, Dockerfile, migrations) [todo]
## Step 14 — Load test + polling/SSE tuning [todo]
## Step 15 — Docs + handover [todo]
## Step 16 — Final audit [todo]

## Deferred
- Live `DATABASE_URL` dump: `docs/db_schema.md` is reconstructed from code; overwrite via `scripts/dump_schema.py` against real n8n DB when available.
- Staging Railway HTTPS login check: needs Railway project access (unavailable locally); Dockerfile + migrate-on-boot CMD are ready for it.
