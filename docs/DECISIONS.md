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
- Reliability (hotfix 9B): states are `queued -> sending -> sent|failed` (migration `0012_outbox_sending` adds `claimed_at`). The claim transaction marks rows `sending`, so a concurrent instance never picks them up; `sending` rows older than 2 minutes are reaped to `failed` with `error='delivery state unknown, check WhatsApp'` and no auto-retry. The mirror runs in a SAVEPOINT: any mirror error rolls back only the mirror, the row stays `sent` with `error='mirror_failed: ...'` and an ERROR log. Every row is wrapped in try/except, so one poisoned row never stops the cycle.
- Retry policy (hotfix 9B): auto-retry only when the request provably never reached n8n (`httpx.ConnectError` incl. DNS, `httpx.ConnectTimeout`; transport errors propagate raw from `post_to_n8n` for classification). Read timeouts, HTTP errors and rejections fail at once (`failed` + notify, attempts+1) and wait for the manual retry button, which warns about possible double delivery. Retryable errors keep exp backoff (1m/2m/4m/8m, cap 1h) up to 5 attempts, then `failed` + `outbox_failed` notify. `outbox_id` lets n8n dedupe redeliveries.
- `httpx` moved into production `requirements.txt` (the worker needs an HTTP client; it was dev-only before).
- Pause/resume toggles write contact-scoped `bot_paused`/`bot_resumed` activity rows, so the events show in the deal timeline. A manager send auto-pauses the bot via the `auto_pause_on_manual_reply` setting (default true) — unlike `auto_pause_on_manager` (default false), because a human reply mid-bot-flow would otherwise collide with the bot.
- Chats visibility (hotfix 9B): `/api/chats/*` honors `restrict_managers_to_own` via the linked contact owner (leads without a contact count as unassigned); pause/resume/send return 404 `LEAD_NOT_FOUND` when the lead is gone; retry is author-or-admin (403 otherwise). SSE `new_message`/`bot_event` are filtered the same way per connection (owner cached per `whatsapp_id`).
- SECRET_KEY is optional (default ""): app auth uses opaque random session tokens (sha256 in DB) and nothing signs with it; the variable is kept for operator tooling and future use.

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
## D18. Step 9C visibility rule for dialogs, chats and SSE
- The brief asked for D15, but D15 is taken (tasks/notifications); this lands as D18.
- Decision: dialogs (`/api/dialogs*`), `/api/chats/*` and SSE event kinds
  `new_message`, `bot_event`, `outbox_status`, `bot_paused` obey
  `restrict_managers_to_own` through the *deal* owner, not the contact
  owner: the responsible user is the owner of the most recently updated
  live deal of the linked contact (`services/visibility.py::lead_owner`).
  Without a live deal the contact owner applies; without a contact the lead
  counts as unassigned (visible to all).
- Why the deal owner: the deal is the working object (round-robin assigns
  deal owners, handover notifies deal owners); a reassigned deal must move
  visibility with it. The dialogs list filters in SQL (LATERAL managed-deal
  subquery + CASE fallback, paginated), single-object endpoints and the
  per-connection SSE cache use the same helper, so REST and stream agree.

## D19. Step 9C debt-closure notes- Unassign: PATCH distinguishes "field absent" from explicit `null` via
  `payload.model_fields_set` (deals `owner_id`, contacts `owner_id`, tasks
  `assignee_id`); bulk unassign is an explicit `unassign_owner: true` flag
  (mutually exclusive with `set_owner_id`, else 422), because JSON PATCH
  cannot tell "don't touch" from "clear" otherwise.
- Round-robin: `pick_assignee` locks the pre-seeded `deal_assignment` settings
  row (`SELECT ... FOR UPDATE`, migration `0013_round_robin`), so concurrent
  deal creations serialize instead of duplicating picks.
- Notifications: `dedupe_key` is a real column with a partial unique index
  `(user_id, type, dedupe_key) WHERE read_at IS NULL` (migration
  `0014_notify_dedupe`, pre-existing dupes collapsed keeping latest);
  `notify()` inserts with `ON CONFLICT DO NOTHING` and returns pending bus
  events that callers publish only AFTER commit (sync batch flush,
  notify/outbox cycles, deal create). Pre-commit ghosts are gone by
  construction; `test_realtime` publishes explicitly like production code.
- Dialogs list: `crm_conversation_state` carries `last_message_at`,
  `last_message_direction`, `last_message_preview` (migration `0015`,
  backfilled), refreshed by the sync worker per batch and by the outbox
  worker on send. The list orders/filters/paginates purely in SQL
  (20k dialogs < 200ms); no new indexes on `knewit_*` (rule 1).
- Worker flags: `OUTBOX_ENABLED`, `NOTIFICATIONS_ENABLED`,
  `REALTIME_ENABLED` (default true) gate each loop independently in
  lifespan; tests disable all four.
- Legacy: `GET /api/dialogs/{wa}/messages` (explicit columns, auth,
  lead-404) replaces the frontend's `/api/leads/*/messages` call;
  `legacy_bot.get_lead` no longer uses `SELECT *`.
- Frontend polling: `useStreamStatus()` (shared `useSyncExternalStore`)
  exposes the singleton SSE state; message/outbox queries poll only while
  disconnected and go quiet on `connected`.
- `SECRET_KEY` is optional: nothing signs with it (opaque session tokens),
  so requiring it only broke local setups; kept for tooling/future use.
- Board `sum()` cartesian SAWarning: aggregates now read the subquery's own
  columns instead of pulling `crm_deals` into the outer FROM.

## D20. Step 12 analytics notes
- Endpoints: `GET /api/analytics/overview` (funnel + summary + dynamics +
  managers + bot + sources + tags in one call) and `GET /api/analytics/export`
  (`section=funnel|dynamics|managers|objections|abandoned|sources|tags|lost_reasons`,
  CSV with UTF-8 BOM via the shared `csv_stream`). Both require auth, both
  roles; validation errors are `INVALID_PERIOD` / `PERIOD_TOO_LARGE` (422),
  unknown pipeline is 404, unknown owner is 422.
- Period params are calendar dates (`date_from`/`date_to`, default last 30 days
  incl. today, max 366 days) interpreted as day boundaries in
  `settings.default_timezone` (default Asia/Almaty) and converted to UTC for
  comparisons; DB stores UTC. Daily/weekly buckets are grouped in SQL with
  `DATE(col AT TIME ZONE :tz)`.
- Funnel is cohort-based: deals created in the period in the selected pipeline
  (default pipeline when omitted). `reached` = distinct deals with a
  `crm_deal_stage_history.to_stage_id` row (any time, so late moves still count)
  UNION bot `knewit_events.to_stage` mapped via `bot_stage_key`, with the
  current stage as fallback for deals without history. Step conversion =
  reached[i]/reached[i-1]; overall = cohort `won` deals / first-stage reached;
  `total_finished` = cohort won deals (not last-stage reach, because won/lost
  deals keep their open stage). Average time on stage uses completed stays only
  (closed by a later move); bottleneck = reached stage with the lowest step
  conversion.
- Summary: `new_leads` from `knewit_leads.created_at`; `trials_booked` from
  `deals.trial_at`; won/lost by `closed_at`; lost breakdown by reason (NULL
  reason reads as "Без причины").
- First response (managers) = first `in` message -> first later `out` message
  (bot or manager) for the linked `whatsapp_id`, averaged in hours; dialogs
  without an outgoing reply are excluded.
- Bot: in/out counts + `AVG(response_time_ms)` over outgoing messages,
  `SUM(tokens_used)` total and per day; handover = leads created in the period
  with current status `МЕНЕДЖЕР` or any `transferred_to_manager` event;
  closed-without-manager = the rest; `last_objection` top 10; abandoned =
  cohort grouped by `current_stage`.
- Sources group contacts created in the period by current `source` value
  (empty -> `unknown`); won counts/sums join deals created in the period.
  Tags use deal tags (`crm_entity_tags` entity `deal`): `deals` created in the
  period, `won`/`won_sum` closed in the period.
- Visibility: deal/lead-derived aggregates honor `restrict_managers_to_own`
  (restricted managers are forced onto their own scope; a foreign `owner_id`
  reads as 404 like the deals endpoints). The managers roster itself always
  lists active users (per-owner by construction). Aggregates are bounded
  (stages/users/tags), so no pagination: drill-down reuses the paginated
  `GET /api/deals` list (`stage_id` + created bounds) in a modal.
- No index was created on `knewit_*` (rule 1). Migration
  `0017_analytics_indexes` adds `IF NOT EXISTS` indexes on `crm_*` hotspot
  columns only (deals created/closed/trial/status/pipeline, history
  deal+at/to-stage, contacts created/source, tasks done/due, entity-tags
  composite). Analytics reads `knewit_*` directly; volumes are hundreds of
  rows, so no materialization worker is needed (revisit if traffic grows 100x).
- Frontend `/analytics` (recharts 2.x): period presets + custom range, funnel
  and owner filters, day/week toggle, KPI cards, funnel bar (click = drill-down
  modal), dynamics lines, sortable funnel/manager tables, CSV buttons. API
  module uses hand-written types (same precedent as D17); `src/api/types.ts`
  untouched.
- Drive-by fixes required by the gates (all pre-existing, behavior-neutral):
  `contacts.tsx` toast variant `"destructive"` -> `"error"` (typecheck was red),
  one intentional `set-state-in-effect` documented with an inline disable
  comment, prettier-only reformat of 4 contacts files.

## D21. Step 13 settings notes
- No migration: every tab reads/writes existing tables (`crm_settings` KV,
  `crm_quick_replies`, `crm_sessions`, `crm_outbox`, `crm_activity_log`).
  New routers: `settings.py` (`/api/settings`, `/api/settings/bot-stages`,
  `/api/settings/integrations`), `activity.py` (`/api/activity`,
  `/api/activity/entities`); extensions in `chats.py` (quick-reply CRUD +
  global `GET /api/chats/outbox`) and `auth.py` (profile + sessions).
- Curated settings keys with code defaults: `restrict_managers_to_own=false`,
  `auto_pause_on_manager=false`, `auto_pause_on_manual_reply=true`,
  `deal_assignment.mode=unassigned` (round-robin keeps its `last_index` across
  mode switches; unknown keys are rejected, never stored). PATCH logs
  `settings_updated` into the activity journal.
- `bot-stages` returns live `DISTINCT current_stage/status` from `knewit_leads`
  (read-only; rule 1 safe) for the stage-editor dropdowns.
- Quick replies: list stays open to all authenticated users (dialog composer
  needs it); create/update/delete are admin-only with `QUICK_REPLY_EXISTS` 409.
- Sessions are strictly own-only; revoking the current session is 422
  (`CANNOT_REVOKE_CURRENT`, use logout); `revoke-others` powers "exit on other
  devices". Profile self-edit covers `name` only (email stays the login key);
  password change already existed and revokes other sessions.
- Integrations: bot DB probe is three read-only `COUNT(*)` with latency and a
  sanitized `unreachable` error (raw DB errors may carry host info, so they are
  only logged server-side). n8n status reports `N8N_SEND_WEBHOOK_URL` as-is:
  it contains no secret by design (the secret travels in the `X-CRM-Secret`
  header, which is never returned by any endpoint).
- Profile display prefs (timezone, notification sound) live in localStorage
  like the theme (precedent `lib/theme.ts`); the instance default timezone /
  currency stay env-based (`DEFAULT_TIMEZONE` / `DEFAULT_CURRENCY`) because
  analytics buckets and API semantics depend on them server-side.
- `/settings` route is open to all authenticated users; the 8 admin tabs are
  gated inside the page (`ForbiddenPage` for managers) while `Профиль` is
  available to everyone, so the nav entry is no longer admin-only.

## D22. Step 14 hardening notes
- Middleware order (execution, outermost first): CORS (only when
  `ALLOWED_ORIGINS` is set, so preflights short-circuit before auth) →
  RequestId → Metrics → SecurityHeaders → RateLimit → BodyLimit → SessionAuth.
  `CORSMiddleware` uses explicit origins + credentials; empty list means
  same-origin only (the SPA is served by the same container).
- Security headers on every response: strict CSP (`script-src 'self'`, no
  `unsafe-inline`; inline `style` stays allowed because React writes it via
  CSSOM and blocking style attributes breaks UI libs silently), `X-Frame-
  Options: DENY` (+ `frame-ancestors 'none'`), nosniff, strict referrer,
  HSTS (always sent; browsers ignore it over plain HTTP), minimal
  Permissions-Policy.
- Rate limiting is two-tier: per-IP sliding window over all `/api` (600/min,
  429 + `Retry-After`) plus per-user cap on message sends (30/min). Login
  keeps its own failed-attempt rules (D9). Limits come from Settings per
  request; hit counters are process-local (single container, D9). The shared
  test settings disable the API-wide limiter (`rate_limit_enabled=False`)
  because high-volume tests (round-robin over the whole roster, 20k dialogs)
  are legitimate bursts; the limiter itself is covered by dedicated tests.
- Request bodies are capped (`MAX_REQUEST_BODY_BYTES`, 10MB) by a pure-ASGI
  middleware covering both `Content-Length` and chunked uploads (413).
- `test_authz_matrix.py` sweeps every OpenAPI route: anonymous must 401
  everywhere except health/ready/login; managers must 403 exactly on the
  `ADMIN_ONLY` allowlist and never 401/403 elsewhere. New admin routes must
  extend the allowlist deliberately; a drift test compares its size against
  `Depends(require_admin)` occurrences in source.
- SQLi audit: all queries are parameterized; the single `text(f"...")` in
  `realtime_poller._max_id` now allowlists its two literal table names.
  XSS: no `dangerouslySetInnerHTML` anywhere (backend test scans `frontend/
  src`); client messages render as React text and round-trip verbatim as JSON.
- Password change now rotates fully: all sessions die (including current) and
  a fresh one is issued transparently via Set-Cookie. Login always mints a
  new token (fixation-safe). Deactivation already revoked everything (D9).
- Audit: successful logins, user create/update (role/active/password-reset
  marker, never the hash), exports (filters + row count) and import completion
  go to `crm_activity_log`. Failed logins stay in server logs only (DB flood
  protection); logout is not logged (low value, high volume).
- Sentry is optional on both sides via `SENTRY_DSN` / `VITE_SENTRY_DSN`;
  backend `sentry-sdk` is a pinned prod dep but init is DSN-gated, frontend
  lazy-imports `@sentry/react` only when the build-time DSN exists.
- `/api/metrics` (Prometheus text) needs `Authorization: Bearer $METRICS_TOKEN`;
  unconfigured reads as 404, wrong token as 403. Session cookies are
  deliberately not accepted (token URLs leak into browser history). Counters
  are in-process with route-template labels (bounded cardinality).
- Shutdown: worker cancel is bounded by `SHUTDOWN_TIMEOUT_SECONDS` (uvicorn
  gets `--timeout-graceful-shutdown 20` in Docker too); pool always disposed.
  Pool sizes/timeouts/recycle are env-configurable (`DB_POOL_*`).
- Perf (100k messages, EXPLAIN-driven): board totals went from 32 point
  queries to one `GROUP BY`; `managers_section` from 5×N queries to 6 grouped
  ones; bot message stats merged into one scan; `overview()` runs the five
  read-only sections concurrently on separate connections (5 per overview —
  fits the default 5+5 pool; raise `DB_POOL_SIZE` if many managers open
  analytics at once). Measured wall time: dialogs ~100ms, messages ~60ms,
  board ~250ms, analytics 120–350ms depending on period/roster. `knewit_*`
  index proposals live in `docs/DB_RECOMMENDATIONS.md` (never applied by us).
- Deps: `pip-audit` clean after `fastapi 0.115.6 -> 0.134.0` (+ explicit
  `starlette==1.7.0`), `python-multipart 0.0.20 -> 0.0.32`, new
  `sentry-sdk==2.71.0`; `npm audit` clean. Chose the oldest fastapi permitting
  starlette>=1.3.1 to minimize API drift; full suite green, OpenAPI shapes
  unchanged (no frontend type churn).

## D23. Step 9D part B notes (n8n send workflow + targeted hardening)
- `docs/n8n/crm-send-message.workflow.json` is the «CRM Send Message»
  workflow: Webhook POST (responseNode) → IF `X-CRM-Secret` vs
  `$env.N8N_WEBHOOK_SECRET` (401 `{ok:false}` on mismatch) → Code dedupe
  by `outbox_id` via workflow static data (repeat = 200 without resend)
  → HTTP send through the same WhatsApp provider node as the main bot
  workflow (operator replaces the placeholder, same credentials) →
  Respond `{ok:true, provider_message_id}` or `{ok:false, error}`.
  Multi-instance n8n replaces the Code pair with a Postgres check on its
  own `n8n_processed_outbox` table (SQL in `docs/n8n/README.md`); bot
  schema is never touched.
- Main bot + cron follow-up patch (same README): after the incoming write
  to `knewit_messages`, a read-only Postgres node
  `SELECT bot_paused FROM crm_conversation_state WHERE whatsapp_id = $1`
  (missing row = false) gates the AI agent: `true` ends the execution,
  `false` continues. Only SELECT, no triggers/writes to `knewit_*`.
- Analytics visibility: `analytics_managers_visible` in `crm_settings`
  (default true), exposed via `GET/PATCH /api/settings`. When false,
  non-admin `GET /api/analytics/overview|export` answer 403; admins always
  pass. Default true keeps current behavior (managers see analytics);
  hiding is explicit, not a scope leak (unlike 404-hiding in deals).
- Export hardening: `services/export._cell` prefixes values starting with
  `= + - @ TAB CR LF` with `'` (CSV and XLSX share the helper), so
  exported cells can never become spreadsheet formulas.
- Import hardening: 2 MiB per-file cap (`IMPORT_MAX_BYTES`) enforced while
  streaming the upload in 64 KiB chunks (413 `REQUEST_TOO_LARGE`); other
  endpoints stay under the global `BodyLimitMiddleware` (10 MiB).
- Outbox PII: `crm_outbox.error` stores only `format_outbox_error(exc)`
  (`ClassName: first line`, max 200 chars, SQL params dropped with later
  lines); logs carry only outbox ids and error class names, never message
  bodies or `whatsapp_id` phones (also scrubbed from `bot_bridge` and
  `deal_flow` logs; `last_message_preview` stays functional, not logged).

## D24. Step 15 production deploy notes
- One container serves API + SPA + all four in-process workers. The
  entrypoint (`scripts/docker-entrypoint.sh`) runs
  `alembic upgrade head` first, then `uvicorn backend.app.main:app
  --workers 2 --proxy-headers --forwarded-allow-ips="*" (superseded by D26: 1 worker)`. (The brief wrote
  `app.main:app`; the repo layout is `backend.app.main`, so the real
  module path is used.)
- Two uvicorn workers each run lifespan loops, but every loop is
  advisory-locked (sync 91030001, notify 91030002, outbox xact-lock,
  realtime poller cursors converge), so at most one worker — or one
  container, when Railway scales horizontally — does each job. No worker
  changes were needed for `--workers 2`.
- Concurrent boots serialize migrations in `alembic/env.py` with a
  session-level `pg_advisory_lock(91030000)` (same numeric namespace as
  the worker keys, otherwise unused): the holder migrates, the rest block
  and then no-op. Lock + unlock wrap the run on a dedicated connection.
- Single DB role `crm_app` for both migrate and serve (single container,
  single `DATABASE_URL`): `CONNECT` + `CREATE` on schema public (so
  migrations own new `crm_*` tables outright), `SELECT` on `knewit_*`,
  column-level `UPDATE (current_stage, previous_stage, updated_at)` on
  `knewit_leads`, `INSERT` on `knewit_events`/`knewit_messages`, `USAGE`
  on their id sequences. Negative GRANT checks in `docs/DEPLOY.md` prove
  the app cannot alter bot schema even on a bug. A separate migrate-only
  role was rejected as pointless complexity for one container.
- Staging gets its own Postgres seeded from `tests/fixtures/` and never
  touches the prod n8n database: staging backfill and `bot_bridge` writes
  would otherwise reach live clients.
- Base images pinned by digest (`python:3.12.14-slim`,
  `node:20.19.0-slim`); refresh via `docker buildx imagetools inspect`.
  `VITE_SENTRY_DSN` is baked at build time, which is another reason
  staging and production are separate services (separate builds).
- Migrations must stay backward-compatible (expand → migrate → contract)
  so a code rollback never meets an unreadable schema; `downgrade` is a
  last resort (service stopped, one step, tested locally).
- CI builds the image on every push (no push to a registry — Railway
  builds from source), auto-deploys `develop` to staging, and deploys
  `v*` tags to production behind a GitHub Environment approval, via
  `railway up` with `RAILWAY_TOKEN`. `scripts/smoke.sh` is the
  post-deploy gate (health → login → deals → SSE prologue, opt-in send).

## D25. Step 16a security-audit closure notes
- CI smoke step no longer gates on secrets in `if:`: `SMOKE_PASSWORD`
  always passes through env (possibly empty) and `smoke.sh` skips the
  authenticated checks itself with exit 0. `actionlint` runs as its own
  CI job over `.github/workflows/ci.yml`.
- Interactive docs are off in production (`APP_ENV=production` →
  `docs_url/redoc_url/openapi_url=None`); the SPA fallback explicitly
  404s `/docs`, `/redoc`, `/openapi.json` instead of serving index.html.
  Local/dev keeps full docs.
- Login timing: unknown and inactive accounts burn one full argon2 verify
  against a precomputed random dummy hash, so response time does not
  reveal account existence or status (means within 30% in tests).
- Login rate limiting moved from process memory to `crm_login_attempts`
  (`ip`, `email`, `at` + two composite indexes, migration `0019`,
  opportunistic purge of rows older than 1h on write), so the 5-per-pair
  / 20-per-email budgets hold across `--workers 2` and instances.
  The per-email block is soft: after 20 failures, requests from the
  owner's last session IP still pass (unknown emails have no owner IP
  and stay blocked); 429 carries `Retry-After` computed from the oldest
  counted failure.
- 422 details are `{loc, msg, type}` only: raw `input` (passwords, message
  texts) and `ctx` are never echoed back. Frontend treats details as
  opaque `unknown`, so nothing depended on `input`.
- Sentry `before_send` (`scrub_sentry_event`, backend + `beforeSend` in
  `main.tsx`) drops request bodies and SQLAlchemy breadcrumb `params`;
  statement text and method/URL are kept for triage. Span-level
  `db.params` (transactions) are out of scope — `traces_sample_rate`
  stays 0.0, so no spans leave the process.
- n8n send workflow: Postgres dedupe (`n8n_processed_outbox`,
  `INSERT ... ON CONFLICT DO NOTHING`) is primary — the `COUNT(*)`
  check always yields one row so the IF branch never stalls; static-data
  Code is documented as fallback only. Secret check requires a non-empty
  header plus case-sensitive equality (an empty env secret no longer
  matches an empty header).
- Accepted risk (2026-10-08): the n8n `CRM Send Message` dedupe is
  sequential only. Two concurrent requests with the same `outbox_id`
  can both miss `n8n_processed_outbox` and double-send. Considered
  unlikely: the outbox claim is `SKIP LOCKED`, manual retry is allowed
  only from `failed`, the n8n send timeout (10 s) equals the CRM
  timeout, and `sending` rows are reaped after 120 s (`_reap_stale_sending`),
  so the first request has finished before any retry. Revisit if
  parallel sends or repeated duplicates appear; the fix is a pre-send
  `pending` row with `INSERT ... RETURNING` (needs a `status` column).

- Removed legacy `/api/leads*` (audit C1, 2026-10-08): the router
  `routers/legacy_bot.py` had no visibility checks, so any logged-in
  manager could read every lead, phone, message and event even with
  `restrict_managers_to_own`. The frontend never called it. Removed the
  router, its `main.py` include, the `types.ts` paths (regenerated via
  `npm run gen:api`), and the tests that used it; `test_legacy_bot.py`
  keeps the migration test and asserts the routes now return 404.
  Health tests use `/api/dialogs` as the protected route.
- DB-backed tests fail instead of skipping under CI (audit H4, 2026-10-08):
  `conftest.db_available` calls `pytest.fail` when `CI` is set and Postgres
  is unreachable. Locally it still skips, so developers without a DB are
  not blocked. Not yet done from P1-7: CI deploy gates (H3) need owner
  decisions (a `develop` branch does not exist; `workflow_dispatch` does not
  deploy production; `production` environment reviewers must be set in GitHub).
- Test schema for knewit_* follows production (P0-4, 2026-10-09):
  `tests/fixtures/knewit_schema.sql` is rebuilt from `schema_dump.sql`
  (PK `id` on leads, `whatsapp_id` UNIQUE, no FK between knewit_* tables,
  `updated_at` trigger, prod defaults). The old fixture had a TEXT PK and
  cascading FKs, which hid cleanup bugs. Tests that deleted leads and relied
  on cascades now delete messages/events/followups first. `docs/db_schema.md`
  is rebuilt from the dump. The composite index missing in production makes
  the idle-sync timing test borderline (~1.0 s); that is tracked under P2-6.
- CRM ↔ n8n contract test (P0-4 tail, 2026-10-09): `tests/test_integration_contract.py`
  checks that code only references contracted `knewit_*` tables (scan of SQL
  FROM/INTO/UPDATE/JOIN targets in `backend/app`), that the contracted columns
  and key types exist in the test schema, that `knewit_leads.whatsapp_id` is
  UNIQUE, and that no FKs exist between `knewit_*` tables. The contract is a
  hand-kept list in the test: extend it together with any new CRM query.

## D26. Single uvicorn worker until the realtime bus is cross-process (P1-1, step 1)
- `scripts/docker-entrypoint.sh` starts uvicorn with `--workers 1` (was 2, see D24).
- Why: `services/event_bus.py` is process-local. With two workers, a publish in one
  process (outbox status, task created, bot events from the poller) never reaches SSE
  clients connected to the other one. Advisory locks already keep the background loops
  single-run, so the only cost of one worker is HTTP throughput.
- Step 2 (done): a subscriber whose queue overflows gets one `resync` event instead
  of a silently dropped backlog (`event_bus._resync`); the frontend refetches the
  core lists on `resync` and after any reconnect (events during a drop are lost).
- Not yet done: LISTEN/NOTIFY bus (P1-1 step 3). Until step 3, do not add workers
  or replicas (DEPLOY.md §5). Owner approved deferring step 3 until scale-out.

## D27. Operational gauges on /api/metrics (P1-11)
- `services/ops_metrics.py` adds, read-only, on each scrape:
  `crm_sync_lag_seconds` and `crm_sync_full_lag_seconds` (age of the sync markers in
  `crm_settings`), `crm_realtime_poll_age_seconds` (age of the last successful poll in
  this process, `services/metrics.mark_cycle`), `crm_outbox_oldest_due_seconds{status}`
  for `queued` (since `next_attempt_at` or `created_at`) and `sending` (since
  `claimed_at`), `crm_unanswered_dialogs` (last message `in`, bot not paused, older
  than 10 min), `crm_sse_subscribers`. Plus the existing outbox counts and pool gauges.
- A gauge without a known value is omitted (sync lag before the first cycle), but
  empty backlogs read as 0.
- Not included: failures per hour. `crm_outbox` has no `failed_at` column, so this
  needs one (an expand migration) or a log-based counter. Use
  `crm_outbox_messages{status="failed"}` for the current total meanwhile.
- The unanswered gauge uses the P0-5 rule with the default 10-minute threshold. It is
  not an alert; alerting is the P0-5 work.
- AI replies after takeover are not included: they need the bot/manager event mapping.

## D28. Unanswered dialogs (P0-5)
- One definition in `services/unanswered.py`: the last message is `in`, the bot is not
  paused, and the message is older than the threshold (`unanswered_after_minutes` in
  `crm_settings`, default 10, range 1–1440, editable through `PATCH /api/settings`).
  The list filter `needs_reply=true`, the per-row `needs_reply` flag, the
  `crm_unanswered_dialogs` gauge and the notifications all use it.
- Detection runs in the notify worker cycle (60 s, advisory-locked). Each unanswered
  episode, keyed by `unanswered:<whatsapp_id>:<last_message_at>`, notifies the dialog
  assignee, else the managed-deal owner, else the contact owner, else all active managers.
  A new client message starts a new episode. The key is checked against all notifications,
  read or not, so a read notification does not come back every cycle.
- Only episodes from the last 24 h alert. Older unanswered dialogs stay visible in the
  filter but do not notify, so the first run after deploy does not flood managers with
  history. Check the initial count of the filter before relying on it.
- Read-only for `knewit_*`; the only writes are `crm_notifications` rows through `notify()`.
- Not included: an alert to the admin for dialogs nobody sees (no owner and no managers),
  and a settings UI for the threshold (API only for now).
