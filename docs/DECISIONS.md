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
