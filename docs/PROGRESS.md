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
## Step 5 — Chat: SSE realtime + outbox + n8n webhook [done]
- Outbox half shipped in Step 9/9B below (queue, worker, webhook, mirror); realtime shipped in Step 10 (SSE + event bus).
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
## Step 8b — Tasks and notifications [done]
- [x] Brief arrived out of PROGRESS order; covers tasks page + notifications + assignment + automations
- [x] Migrations `0007` (notifications, automations) + `0008` (standalone tasks); tasks API gaps (`/complete`, `mine`/date filters, bulk reschedule); notifications list/read/read-all; automations CRUD (admin)
- [x] Workers: 60s notify loop (overdue/due-soon deduped) + automations; sync handover (urgent task + notify, opt-in autopause), locked-stage and unread-transition notifies; round-robin assignment
- [x] Frontend: /tasks (groups, week view, RHF+zod modal, checkbox, bulk links), bell with count + dropdown + deep links
- [x] 99 backend tests + tsc/eslint/vitest green; 3 E2E green; manual handover/task/bell curl verified
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

## Step 9C — Audit debt closure [done]
- [x] Unassign: PATCH deals/contacts/tasks honors explicit `null` via `model_fields_set`; bulk `unassign_owner` flag (422 on conflict with `set_owner_id`); `test_unassign.py` per entity
- [x] Round-robin: `SELECT ... FOR UPDATE` on pre-seeded `deal_assignment` row (migration `0013_round_robin`); parallel-creation test proves even split
- [x] Notifications: `dedupe_key` column + partial unique index (migration `0014_notify_dedupe`), `INSERT ... ON CONFLICT DO NOTHING`, bus publish only after commit (callers thread pending events); concurrent-dedupe + no-precommit-publish tests
- [x] Dialogs: `last_message_at/direction/preview` on conversation state (migrations `0015_dialogs_list` + `0016_dialogs_index` for the ordering, backfilled), refreshed by sync/outbox workers, list orders/paginates/counts in SQL (20k dialogs ~80ms, NULLS LAST)
- [x] Worker flags: `OUTBOX_ENABLED`/`NOTIFICATIONS_ENABLED`/`REALTIME_ENABLED` (default true) gate each loop; `.env.example`; independence test; tests disable all four
- [x] Legacy: `GET /api/dialogs/{wa}/messages` (explicit columns, auth, lead-404), frontend switched off `/api/leads/*/messages`, no more `SELECT *`
- [x] Visibility (D18): dialogs/chats/SSE (`new_message`, `bot_event`, `outbox_status`, `bot_paused`) via managed deal owner; admin/manager matrix tests (REST + live SSE)
- [x] Frontend: `useStreamStatus()` shared store; message/outbox polling only while SSE disconnected (+ status unit test)
- [x] README rewritten (entrypoint, migrations, env, workers, n8n, deploy, tests)
- [x] Re-audit 2026-10-01: all 10 items verified present in tree; targeted suites green
  (unassign, round-robin, notify, dialogs+pagination incl. 20k case, worker flags, legacy,
  visibility matrix, realtime, outbox, auth, users); ruff + tsc/eslint/vitest green;
  dialogs pagination and messages route hand-checked on a live server.
  Note: never run two pytest processes against one Postgres — parallel runs caused
  flaky cross-talk failures in test_dialogs.py; sequential runs are green.
- [x] `tsc/eslint/vitest` run locally (Node 20 at `/tmp/opencode/node`): typecheck, eslint,
  prettier, 29 vitest, all green

## Step 9D — n8n send workflow + targeted hardening (part B) [done]
- [x] `docs/n8n/README.md` + `docs/n8n/crm-send-message.workflow.json`: «CRM Send Message» (Webhook POST + `X-CRM-Secret` 401 → дедуп по `outbox_id` через static data → отправка тем же WhatsApp-провайдером, что в основном воркфлоу → Respond `{ok, provider_message_id}` / `{ok:false, error}`; SQL для multi-instance дедупа на своей таблице `n8n_processed_outbox`)
- [x] Инструкция по правке основного воркфлоу бота и Cron follow-up: Postgres-нода `SELECT bot_paused FROM crm_conversation_state WHERE whatsapp_id = $1` (нет записи = false) → IF true завершает выполнение до AI-агента; пошаговая проверка на тестовом чате
- [x] CSV/XLSX-экспорт: `_cell` экранирует значения с `= + - @ TAB CR LF` апострофом (тест обоих форматов)
- [x] Импорт: лимит файла 2 МБ (413) с чтением частями по 64 КБ; остальные эндпоинты под `BodyLimitMiddleware` (10 МБ, тест)
- [x] Outbox: `error` только `ClassName: первая строка` до 200 символов (SQL-параметры отброшены); логи без текстов сообщений и телефонов (`bot_bridge`, `deal_flow` тоже чистые)
- [x] `analytics_managers_visible` (default true) в `GET/PATCH /api/settings`; скрытая аналитика для менеджеров 403, админы всегда проходят (D23)
- [x] PROGRESS: устаревшие `[todo]`-заголовки удалены и нумерация приведена к плану —
  поглощены выполненными шагами: «Step 8 funnel» → Step 12 (аналитика),
  «Step 9 notifications» → Steps 4b (activity log) + 8b (notifications),
  «Step 10 saved views» → Step 6b (kanban + saved views),
  «Step 11 settings» → Step 13b (настройки), «Step 12 roles» → Step 14
  (authz-матрица), «Step 14 load test» → Step 14 (perf на 100k + stream load test).
  Остались genuine todo: Step 13 (deploy), Step 15 (docs), Step 16 (audit).
- [x] Тесты: `test_9d_partb.py` (8 тестов: экранирование CSV+XLSX, лимит 2 МБ
  на preview+import, `format_outbox_error`, короткие ошибки worker/mirror,
  видимость аналитики, наличие n8n-файлов) + обновлённый `test_settings.py`;
  `ruff check` + `ruff format` чистые; смежные сьюты зелёные (settings,
  outbox, contacts_data, analytics, hardening, authz_matrix); фронт
  `tsc/eslint/vitest(29)/prettier/build` зелёные; ручной прогон локального
  сервера (health, login, settings с новым ключом, CSV-экспорт)

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
## Step 12 — Аналитика (страница /analytics) [done]
- [x] Backend: `services/analytics.py` (SQL-агрегаты, см. D20), `schemas/analytics.py`,
  `routers/analytics.py` (`GET /api/analytics/overview`, `GET /api/analytics/export`),
  миграция `0017_analytics_indexes` (только `crm_*`, `IF NOT EXISTS`)
- [x] Воронка когортная (history + `knewit_events` через `bot_stage_key` + fallback текущей
  стадии), конверсии, среднее время, узкое место; drill-down — модалка со списком сделок
  через пагинированный `GET /api/deals`
- [x] Итоги (лиды/пробные/won+сумма+средний чек/потери по причинам), динамика день/неделя,
  менеджеры (в работе, won/lost, конверсия, сумма, первый ответ, задачи),
  бот (in/out, response_time, токены по дням, handover, возражения, заброшенные стадии),
  источники и теги; экспорт 8 секций в CSV
- [x] `backend/tests/test_analytics.py`: 4 теста на фиксированном наборе (ручной пересчёт,
  пустой период, сделки без истории, фильтр owner, недели, валидация, экспорт, скоуп
  `restrict_managers_to_own`); полный backend-сьют зелёный (161 тест: 157 старых + 4 новых;
  по ходу найденный мусор от упавших прогонов в dev-БД вычищен); ручной прогон (overview +
  CSV + 422) на локальном сервере
- [x] Frontend: `recharts@^2.15.4`, `api/analytics.ts` + `pages/analytics.tsx` (пресеты
  периода, фильтры, KPI, графики, сортируемые таблицы, CSV, drill-down), роут `/analytics`
  вместо заглушки; `tsc/eslint/prettier/vitest/build` зелёные (Node 20 найден в
  `/tmp/opencode/node`); drive-by фиксы красных гейтов (см. D20)
- [ ] `docker build` не запускался локально; проверить в CI
## Step 13 — Production deploy (Railway, Dockerfile, migrations) [todo]
## Step 13b — Раздел «Настройки» [done]
- Note: brief numbering collides with the old `Step 13 — Production deploy` placeholder
  above; this step keeps the `13b` suffix like earlier out-of-order briefs, deploy stays [todo].
- [x] Backend: `routers/settings.py` (`GET/PATCH /api/settings` с 4 курируемыми ключами,
  `GET /api/settings/bot-stages` — живые DISTINCT из `knewit_leads` read-only,
  `GET /api/settings/integrations` — пробы БД бота + n8n URL без секрета + счётчики outbox),
  `routers/activity.py` (`GET /api/activity` с фильтрами и пагинацией + `/entities`),
  quick-reply CRUD (admin) и глобальный `GET /api/chats/outbox` в `chats.py`,
  сессии (`GET/DELETE /api/auth/sessions`, `revoke-others`) и `PATCH /api/auth/profile` в `auth.py`
- [x] Вкладки: воронки+стадии (dnd-kit порядок, привязки к этапу/статусу бота, удаление с
  переносом, причины отказа), поля (конструктор), теги, пользователи (CRUD, роли,
  деактивация, сброс пароля), шаблоны, автоматизация+распределение (тумблеры, round-robin,
  редактор правил), профиль (имя, пароль, часовой пояс, звук, сессии), интеграции
  (проверка, журнал outbox с retry), журнал действий (фильтры, пагинация)
- [x] Тесты: `test_settings.py` (9 тестов: roundtrip+частичный PATCH, валидация, 403 менеджеров,
  bot-stages, quick-reply CRUD, две сессии+revoke, профиль+пароль, интеграции без секрета,
  журнал outbox, журнал activity); полный backend-сьют зелёный (170 тестов);
  `settings.test.ts` (prefs + часовой пояс); tsc/eslint/prettier/vitest/build зелёные;
  ручной прогон всех новых эндпоинтов и SPA `/settings` на локальном сервере
- [ ] `docker build` не запускался локально; проверить в CI
## Step 14 — Hardening [done]
- [x] Заголовки (CSP без unsafe-inline для скриптов, DENY, Referrer-Policy, HSTS,
  nosniff) + CORS только из `ALLOWED_ORIGINS`; лимиты (per-IP 600/мин, отправка
  30/мин, логин отдельно), лимит тела 10МБ (413); всё покрыто `test_hardening.py`
- [x] Автотест `test_authz_matrix.py`: sweep всех роутов OpenAPI (401 без сессии;
  403 менеджерам ровно на `ADMIN_ONLY`; drift-контроль по коду) — разрывов нет
- [x] SQLi/XSS: параметризация везде (allowlist в poller), innerHTML-тест, round-trip
  вредоносного контента как текст; ротация сессии при смене пароля (тест);
  аудит входов/ролей/удалений/экспорта/импорта (тесты через activity log)
- [x] Sentry backend+frontend (опционально по DSN), `/api/metrics` за токеном (тесты);
  graceful shutdown с таймаутом, пул с лимитами, healthcheck с БД + Dockerfile
  HEALTHCHECK; `pip-audit` чист (fastapi→0.134.0, starlette==1.7.0, multipart→0.0.32),
  `npm audit` чист, версии закреплены
- [x] Perf на 100k сообщений: EXPLAIN-анализ, board GROUP BY, managers GROUP BY,
  параллельные секции overview; замер: диалоги ~100мс, сообщения ~60мс, board ~250мс,
  аналитика 120–350мс; миграция `0018_perf_indexes` (только `crm_*`);
  `docs/DB_RECOMMENDATIONS.md` (knewit_* — применять осознанно, не нами)
- [x] `scripts/backup.sh` + `docs/BACKUP.md`: pg_dump nightly, ротация, restore
  smoke-тест пройден (dump → scratch restore → counts → drop)
- [x] Полный backend-сьют зелёный; ruff + tsc/eslint/prettier/vitest/build зелёные;
  ручной прогон (заголовки, лимиты, метрики, журнал, бэкап) на локальном сервере
- [x] Старый плейсхолдер «Load test + polling/SSE tuning» поглощён шагом: perf-анализ
  и скрипт `scripts/perf_seed_100k.sql` + `scripts/stream_load_test.py` (шаг 10) закрывают тему
- [ ] `docker build` не запускался локально; проверить в CI
## Step 15 — Docs + handover [todo]
## Step 16 — Final audit [todo]

## Deferred
- Live `DATABASE_URL` dump: `docs/db_schema.md` is reconstructed from code; overwrite via `scripts/dump_schema.py` against real n8n DB when available.
- Staging Railway HTTPS login check: needs Railway project access (unavailable locally); Dockerfile + migrate-on-boot CMD are ready for it.
