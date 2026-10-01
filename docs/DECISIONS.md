# Architecture Decisions

All decisions are in English for the codebase. UI texts stay in Russian.

## D1. Sessions, not JWT
Server-side sessions in `crm_sessions` table, token in httpOnly + Secure + SameSite=Lax cookie.
Why: revocable, simpler security model, no token refresh complexity.

## D2. One bot lead = one contact + one deal by default
Link by `whatsapp_id`. Manager creates a new deal manually for repeat purchases.
Why: keeps mapping simple and predictable; avoids ambiguous multi-deal sync.

## D3. Two-way stage sync
- Bot changed stage (`knewit_leads.current_stage` / `status`) -> sync worker moves the deal to the stage with matching `bot_stage_key`.
- Manager moved the deal manually -> `stage_locked = true`. Further auto-moves by bot stop; bot changes are only written to history and notify the manager.
- If the target stage has `bot_stage_key`, `bot_bridge` updates `knewit_leads.current_stage` and writes `event_type='manual_stage_change'` into `knewit_events` in one transaction. If no key is set, bot tables are not touched.
- Manager can unlock with the "Return control to bot" button.
Why: manager decision wins, but bot history stays auditable; writes to `knewit_*` go only through `backend/app/services/bot_bridge.py`.

## D4. Realtime without triggers
n8n writes to DB directly, so CRM polls `knewit_messages` / `knewit_events` (by `id > last_seen_id`, every 2-3 sec) and pushes to clients via SSE. Background workers run in-process under `pg_try_advisory_lock` so multiple Railway instances do not duplicate work.
Why: `knewit_*` tables must not get triggers (rule 1); polling + advisory lock is the least invasive option.

## D5. Bot autopause
When lead status becomes `МЕНЕДЖЕР`, CRM creates an urgent task and a notification. Bot autopause: setting `auto_pause_on_manager`, disabled by default.
Why: explicit handover without surprising the client; autopause stays opt-in.

## D6. Manager outbound messages go through outbox + n8n webhook
CRM does not store WhatsApp provider keys. It calls the n8n webhook with a secret, and n8n sends via the provider already used in the bot workflow.
Why: single sender path, no credential duplication.
- Delivery (Step 9): a `crm_outbox` row (`queued`) is POSTed by the worker as `{outbox_id, whatsapp_id, text}` to `N8N_SEND_WEBHOOK_URL` with header `X-CRM-Secret: N8N_WEBHOOK_SECRET`. On `{"ok": true}` the row becomes `sent` (`sent_at`, `provider_message_id`) and `bot_bridge.insert_outgoing_message` mirrors it into `knewit_messages` as `direction='out', message_type='manager', tokens_used=0`, stamped with the lead's current stage. `crm_outbox.knewit_message_id` links the mirrored row so the timeline shows the sender's name.
- Reliability: failures do `attempts+1` with exponential backoff (1m/2m/4m/8m, cap 1h via `next_attempt_at`); after 5 attempts the row becomes `failed` and the sender gets an `outbox_failed` notification. HTTP calls run outside DB transactions; outcomes apply with a compare-and-set on `status='queued'`, and `outbox_id` lets n8n dedupe redeliveries — repeated runs never double-send.
- `httpx` moved into production `requirements.txt` (the worker needs an HTTP client; it was dev-only before).
- Pause/resume toggles write contact-scoped `bot_paused`/`bot_resumed` activity rows, so the events show in the deal timeline. A manager send auto-pauses the bot via the `auto_pause_on_manual_reply` setting (default true) — unlike `auto_pause_on_manager` (default false), because a human reply mid-bot-flow would otherwise collide with the bot.

## D7. Soft delete
`deleted_at` for contacts and deals. Hard delete by admin only.
Why: protects against accidental data loss, keeps audit trail.

## D8. Step 1 skeleton notes
- Pytest modules live in `backend/tests/`; SQL fixtures stay in `tests/fixtures/` (referenced by `docker-compose.yml` and `scripts/seed_local.py`).
- SQLAlchemy engine lifecycle belongs to the app (`lifespan`, `app.state`), never to module globals — globals bind asyncpg connections to the first event loop and break tests/reloads.
- `/api/ready` is public alongside `/api/health` so orchestrators can probe readiness without credentials.
- `alembic.ini` uses a repo-root-relative `script_location = backend/alembic` so `alembic -c backend/alembic.ini` works from the repo root (CI, dev).
- Ruff ignores `B008` because `Depends(...)` in endpoint defaults is the standard FastAPI idiom.

## D9. Step 2 auth notes
- Cookies: `crm_session` (httpOnly, Secure per `COOKIE_SECURE`, SameSite=Lax, 14 days)
  + `crm_csrf` (readable by JS) for double-submit CSRF. The CSRF token hash is stored
  on the session row, so a token is bound to its session, not just to the browser.
- CSRF is required for unsafe `/api/*` methods, except `POST /api/auth/login`
  (no session exists yet there; SameSite=Lax is the protection). Auth is enforced in
  `SessionAuthMiddleware` so legacy routers are covered too; `require_user` /
  `require_role('admin')` dependencies expose the current user to handlers.
- Login rate limit is in-memory: 5 failures / 10 min per (IP, email) plus
  20 failures / 10 min per email across all IPs (rotating IPs still trips
  it); success resets both. A spoofed `X-Forwarded-For` prefix is harmless:
  the IP is the entry just before the last `TRUSTED_PROXY_HOPS` values
  (default 1, i.e. the last value added by our proxy), falling back to the
  direct peer when the chain is shorter or hops is 0.
  Justification: deploy target is a single Railway container, so a process-local
  store is sufficient and avoids an extra table. Revisit if workers scale out.
- Emails are normalized (strip + lowercase) before lookup/storage; passwords use
  argon2 (`argon2-cffi`), minimum length 10, enforced by Pydantic and bootstrap.
- First admin is bootstrapped at startup from `ADMIN_EMAIL`/`ADMIN_PASSWORD` only
  when zero admins exist; afterwards the variables are ignored. Deactivating or
  demoting the last active admin is rejected (`LAST_ADMIN`). Deactivation revokes
  all sessions; password change revokes all other sessions.
- Step 0 Basic Auth removed entirely (middleware, settings, `.env.example`).

## D10. Step 3 domain and bot sync notes
- Default funnel `Продажи Knewit` is seeded in migration `0003_domain` (idempotent
  `seed_default_funnel`, matched by name). All 14 bot `current_stage` values map to
  open stages via `bot_stage_key`; finals `Клиент`/`Отказ` carry only `bot_status_key`.
  `ДУМАЕТ`/`МЕНЕДЖЕР` are not stages.
- Sync mapping: bot `status` wins (`КЛИЕНТ`/`ОТКАЗ` -> won/lost + `closed_at`);
  otherwise the stage with matching `bot_stage_key`; unknown/NULL stage falls back
  to the first open stage. One managed deal per contact = most recently updated
  non-deleted deal; soft-deleted contacts are skipped, never resurrected.
- Deal `title` is set once at creation; `custom` is merged by key (only
  `CUSTOM_FIELDS` from the lead are refreshed, manager keys survive);
  `trial_at` is refreshed only when `trial_datetime` is non-NULL and differs
  from `last_bot_trial_at` (NULL never erases a manager value);
  `contact.name` is refreshed only while it still matches `last_bot_name`
  (migration `0009_sync_snapshot`); new-deal history uses `source='system'`, bot moves `'bot'`,
  `changed_by=NULL`. Blocked moves (stage_locked) write `bot_stage_blocked` to
  `crm_activity_log`, not to stage history (nothing moved); manager notification
  delivery is Step 9.
- `bot_bridge.update_bot_stage` joins the caller's transaction (no commit inside);
  it no-ops when the stage is unchanged and raises `BotLeadNotFoundError` otherwise.
- Worker holds session-scoped `pg_try_advisory_lock` for the whole cycle and
  commits after every batch of 500 (no giant transaction). Incremental cycles
  fetch only leads with `GREATEST(updated_at, last_message_at)` newer than
  `last_synced_at` minus a 2-minute overlap; a full reconciliation runs when
  `last_full_synced_at` is older than 10 minutes (both markers in
  `crm_settings`). Each batch preloads states/contacts/managed-deals with
  `IN` queries, unread counts with one `GROUP BY`, stage tops with one
  `GROUP BY`, and handover tasks with one query. Interval/flag via
  `SYNC_ENABLED`/`SYNC_INTERVAL_SECONDS`.

## D11. Step 4 domain REST API notes
- Reads are open to all authenticated users; mutations of funnel (pipelines/stages),
  custom-field definitions, and lost reasons are admin-only. Managers do full tag
  CRUD and note CRUD (foreign notes: delete by author or admin).
- `crm_deals.position` is `NUMERIC(20,10)` (migration `0004`, fractional indexing);
  I/O uses float. Same-stage `move` only reorders (no lock/history/bridge);
  cross-stage `move` locks, records manager history, and calls `bot_bridge` when the
  target has `bot_stage_key` (missing bot lead logs a warning, manager move stands).
- New deals only into open stages; `lost` requires `lost_reason_id`; reopening
  clears `closed_at`/`lost_reason`. Stage delete with deals needs `to_stage_id`
  (query param); pipeline delete with stages is refused. `bulk` (max 200 ids) is
  all-or-nothing in one transaction.
- Board: per-column `limit` (default 50) + opaque `next_cursor` per column;
  `cursors` request param is a JSON `{stage_id: cursor}` map. Totals/amounts cover
  the whole column, not the page.
- Custom validation checks only defined fields (unknown keys pass through: the bot
  sync mirrors lead attributes into the same payload); `required` must be present
  and non-null. Tag filter on lists is ANY-match. Scope violations return 404, not
  403, to avoid leaking existence. Soft-deleted contacts hide their deals.
- `restrict_managers_to_own` lives in `crm_settings` (default false = amoCRM-style
  open access); no UI yet (Step 11).

## D12. Step 5 frontend scaffold notes
- New `frontend/` (Vite + React 18 + TS strict + Tailwind v3 + shadcn-style `ui/`
  components, TanStack Query, React Router, lucide-react). Full shadcn CLI setup
  was skipped: hand-written `button`/`input` in shadcn style (cva) are enough for
  the scaffold; adopt the CLI when the component set grows.
- API client: `fetch` with `credentials: include`, CSRF header auto-attached from
  the `crm_csrf` cookie (login exempt), 401 redirects to `/login?next=...`, backend
  error envelope parsed into `ApiError`, toasts for user feedback.
- Backend serves `frontend/dist` when built (else legacy), with SPA fallback for
  non-`/api` paths; hashed `assets/*` are `immutable`, `index.html` is `no-cache`.
- Registry mirror only keeps recent versions, so: `react-router-dom` v7 (v6 pruned;
  used API is v6-compatible), `happy-dom` instead of `jsdom` (jsdom 30 needs newer
  Node than the local 20.19), `openapi-typescript` generates `src/api/types.ts`.
- `docker build` could not run locally (no Docker daemon access); the multi-stage
  Dockerfile is written for CI/Railway. Staging HTTPS check needs Railway access.

## D13. Step 6 kanban notes
- Board columns come from `GET /api/deals/board` (totals/amounts cover the whole
  column); per-column cursor pages merge client-side ("Показать ещё"). Contact
  names/phones join client-side from one cached `/api/contacts?limit=500` call.
- DnD (dnd-kit, pointer distance 4 + keyboard sensor): same-column drops reorder
  only (no lock/history); cross-column drops that hit `lost` open the reason modal
  first, `won` asks for confirmation. Optimistic cache patch with rollback on error.
- Filters live in URL params (shareable) + `crm_saved_views` (migration `0005`,
  own-or-shared visibility, sharing is admin-only). Board/list endpoints accept the
  same filter set; `contact_source` filter was added to deals list+board for this.
- Cards never show fake state: task/unread/bot-pause badges arrive with the chat
  and tasks steps (code has no placeholders for them). Task quick-action and
  "без задач"/"просроченные" filters are deferred to the tasks step.
- E2E (Playwright, chromium headless shell) runs against the built SPA + real API
  and restores the moved seed deal (move back + unlock) so reruns stay green.

## D14. Step 7 card, timeline, and dialogs notes
- `GET /api/deals/{id}/timeline` merges messages, events, stage history, notes,
  tasks, and activity newest-first with a keyset cursor `{at, kind, id}` and
  per-source predicates (numeric compare for bot ids, text compare for uuids).
  Outgoing messages are labeled "Бот" until the outbox (Step 5) adds manager
  attribution. API deal creation now writes a manager-creation history row so the
  лента is complete from birth.
- Fresh conversation rows start read (`last_read_at=now`, unread 0); older rows
  initialize `last_read_at` on first pass. Unread counts incoming messages after
  `last_read_at`. Opening a dialog zeroes it. "Ждут менеджера" is covered by the
  unread filter; route stays `/dialogs` (no rename churn).
- Removed `/api/stats`, `/api/funnel` (analytics returns in a later step) and
  `frontend-legacy/`; `/api/leads*` stay until dialogs fully replace them.
- Card task badges stay deferred (timeline covers tasks); send box and quick
  replies render as explicit "next step" stubs, never fake sends.

## D15. Step 8 tasks and notifications notes
- `crm_notifications` (user FK CASCADE, type, payload with `dedupe_key`, read_at)
  + `crm_automations` (name, is_active, trigger, config, actions). Standalone
  tasks allowed (migration `0008` drops the target check).
- `notify()` dedupes on unread rows with the same (user, type, dedupe_key).
  Worker (60s loop, own xact lock): overdue + due-within-24h reminders keyed per
  task per day; automations evaluated in the same cycle.
- D5 handover in the sync worker: МЕНЕДЖЕР status always creates urgent
  "Ответить клиенту" (due +1h, once per deal) + notifies owner (or all managers);
  `auto_pause_on_manager` setting (default false) gates bot pausing. Fresh
  conversation rows start read; unread 0→N transitions notify the assignee;
  locked-stage bot moves notify the owner (all managers when unowned).
- Round-robin (`deal_assignment` setting, default `unassigned`) rotates by roster
  position among active managers and applies to API-created deals only, plus
  `deal_assigned` notification when owner != creator.
- Automations: triggers `deal_entered_stage` / `no_activity_hours` (optional
  `pipeline_id` scope), actions create_task/assign_owner/add_tag/notify; fire-once
  per (automation, deal) via `automation_fired` activity rows. Mutations are
  admin-only; automations UI itself lands in Settings (Step 11).

## D16. Step 10 realtime notes
- `services/event_bus.py` is a process-local fan-out hub (bounded per-subscriber
  queues, slow consumers drop oldest, publishers never block). Single-container
  deploy, so one event loop is enough; every worker and router shares it.
- `workers/realtime_poller.py` polls `knewit_messages` / `knewit_events` by id
  every 2s (cursors in memory, seeded from current maxima at startup so restarts
  never replay history). It emits `new_message` and `bot_event`; CRM-side changes
  publish directly at their call sites instead: sync bot moves buffer `deal_moved`
  per batch and flush after the batch commit; deals/tasks/chats/outbox publish
  after their own commits. `notify()` publishes `notification` for every created
  row (pre-commit by design, covering workers and API uniformly; subscribers
  refetch, which converges on the next event).
- `GET /api/stream` (SSE, session cookie, no CSRF on GET): `: connected` prologue,
  `event: <type>` + JSON data frames, `: heartbeat` comments every 15s, disconnect
  detection with guaranteed unsubscribe. Per-user filter mirrors REST visibility:
  notifications go only to their owner; deal events respect
  `restrict_managers_to_own` via the published `owner_id`; everything else is
  visible to any authenticated user (dialogs/tasks lists are global).
- Frontend `useEventStream` (mounted once in the layout): one EventSource,
  per-type listeners, TanStack invalidations per event, ping + toast for incoming
  messages in dialogs assigned to the current user, unread count in the tab title.
  Reconnect uses capped exponential backoff (1s→30s); after 6 failures (or no
  EventSource at all) it falls back to 15s polling of the core query keys.
- Tests hit a real limit: httpx's ASGI transport buffers the entire response
  body, so infinite SSE streams hang forever under it. Streaming tests therefore
  boot uvicorn on 127.0.0.1:0 (`live_server` fixture); the 50-connection load
  test (`scripts/stream_load_test.py`) does the same against a dev server.

## D17. Step 11 contacts and data notes
- Normalization lives in `services/normalize.py`: digits-only phones
  (leading 8 -> 7 for 11-digit KZ/RU numbers), `whatsapp_id` stripped of
  `@c.us`/`@lid` suffixes into the same digit space, emails lower+strip.
  Duplicates group live contacts by `phone:<digits>=7+>` or `email:<lower>`;
  no DB column is added (volumes are hundreds, Python grouping is enough).
- Merge (`POST /api/contacts/merge`): deals/notes/tasks re-point to the
  winner, tags union, empty winner fields filled from the loser, loser
  soft-deleted, `contact_merged` + `contact_merged_from` activity rows.
  No rollback (per brief); the source row stays recoverable via restore.
- Contact bulk (`POST /api/contacts/bulk`, max 200): set owner, add tag,
  soft-delete. Static `/duplicates`, `/bulk`, `/export`, `/import/*` routes
  are registered before `/{contact_id}` so FastAPI does not capture them
  as UUIDs.
- Contact timeline (`GET /api/contacts/{id}/timeline`) reuses the deal
  keyset scheme: bot messages/events by `whatsapp_id`, stage history of all
  contact deals, notes/tasks/activity across the contact and its deals.
- Export (`GET /api/contacts/export`, `/api/deals/export`, `?format=csv|xlsx`):
  CSV streams with UTF-8 BOM for Excel; XLSX via `openpyxl` (new production
  dep, added together with `python-multipart` for CSV uploads).
- Import is contacts-only (deals import stays deferred): `POST
  /api/contacts/import/preview` validates mapping+C SV and returns
  per-row errors; `POST /api/contacts/import` stores header+rows inside
  `crm_imports.mapping` (migration `0011_contacts_data`) and processes them
  in a background `asyncio` task with `ok_count`/`error_count`/`errors[:200]`;
  `GET /api/contacts/import/{id}` polls the job.
- Trash (`GET /api/trash`, admin-only) lists soft-deleted contacts+deals;
  restore reuses the existing per-entity endpoints.
- Frontend `/contacts` has tabs Список/Дубликаты/Импорт/Корзина plus
  `/contacts/:id` (deals, timeline, custom fields, tags). Saved views with
  `entity=contact` are supported. `src/api/types.ts` was not regenerated
  (no Node locally); the new API module uses hand-written types.
