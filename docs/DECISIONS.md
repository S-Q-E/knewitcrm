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
- Login rate limit is in-memory: 5 failures / 10 min per (IP, email) -> 429.
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
- Deal `title` is set once at creation; `custom`/`trial_at` are overwritten from the
  lead on every pass; new-deal history uses `source='system'`, bot moves `'bot'`,
  `changed_by=NULL`. Blocked moves (stage_locked) write `bot_stage_blocked` to
  `crm_activity_log`, not to stage history (nothing moved); manager notification
  delivery is Step 9.
- `bot_bridge.update_bot_stage` joins the caller's transaction (no commit inside);
  it no-ops when the stage is unchanged and raises `BotLeadNotFoundError` otherwise.
- Worker uses `pg_try_advisory_xact_lock` (transaction-scoped, pool-safe; auto-released
  on commit/rollback) instead of session-level lock. Backfill pages leads by
  `whatsapp_id` in batches of 500; progress marker `sync_worker.last_synced_at`
  lives in `crm_settings`. Interval/flag via `SYNC_ENABLED`/`SYNC_INTERVAL_SECONDS`.

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
