# KnewIT CRM — amoCRM-style CRM for the WhatsApp course bot

Web CRM for managers of KnewIT (online courses). Clients arrive through a
WhatsApp bot on n8n with an AI agent. The bot writes directly to Postgres
(`knewit_leads`, `knewit_messages`, `knewit_events`, `knewit_followups`);
the CRM lives in the same Postgres in its own `crm_*` tables and never
migrates bot tables (see `docs/DECISIONS.md`, rules 1–2).

**Stack:** Python 3.12 + FastAPI + SQLAlchemy 2.0 (async) + Alembic on the
backend; React 18 + Vite + TypeScript + Tailwind on the frontend. UI is in
Russian; default currency KZT, default timezone Asia/Almaty (Settings).

## Quick start (local)

```bash
docker compose up -d            # local Postgres 16 + seed
pip install -r requirements-dev.txt
alembic -c backend/alembic.ini upgrade head
uvicorn backend.app.main:app --reload --port 8000
```

Open http://localhost:8000, log in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`
(used once to bootstrap the first admin). The entrypoint is
`backend/app/main.py:create_app()`.

Frontend dev (proxy to the API):

```bash
cd frontend && npm ci && npm run dev
```

## Migrations

All CRM tables carry the `crm_` prefix and are created only via Alembic.
The version table is `crm_alembic_version`; `env.py` filters everything
except `crm_*`, so `knewit_*` and other n8n objects are never touched.

```bash
alembic -c backend/alembic.ini upgrade head
alembic -c backend/alembic.ini revision -m "what changed"  # then edit upgrade()/downgrade()
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | — | Full DSN (`postgresql://user:pass@host:port/db`), or PG* parts below |
| `PGHOST` / `PGPORT` / `PGUSER` / `PGPASSWORD` / `PGDATABASE` / `PGSSL` | localhost… | Used only when `DATABASE_URL` is empty |
| `SECRET_KEY` | `""` (optional) | Kept for tooling; auth uses opaque random session tokens |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | — | Bootstrap the first admin once (min 10 chars), then ignored |
| `APP_ENV` / `LOG_LEVEL` | local / INFO | |
| `COOKIE_SECURE` | true | Set `false` for plain-HTTP local dev |
| `DEFAULT_TIMEZONE` / `DEFAULT_CURRENCY` | Asia/Almaty / KZT | |
| `TRUSTED_PROXY_HOPS` | 1 | Trailing X-Forwarded-For entries added by our proxies (Railway = 1) |
| `SYNC_ENABLED` / `SYNC_INTERVAL_SECONDS` | true / 5 | Bot sync worker (leads → contacts/deals, locks, handover) |
| `OUTBOX_ENABLED` / `OUTBOX_INTERVAL_SECONDS` | true / 5 | Manager-message delivery worker |
| `NOTIFICATIONS_ENABLED` | true | Task reminders + automations worker (60s cycle) |
| `REALTIME_ENABLED` | true | Bot-table poller feeding SSE (2s cycle) |
| `N8N_SEND_WEBHOOK_URL` / `N8N_WEBHOOK_SECRET` | — | n8n webhook that sends WhatsApp messages (`X-CRM-Secret` header) |
| `ALLOWED_ORIGINS` | empty (same-origin only) | Extra origins allowed for CORS (credentials on) |
| `RATE_LIMIT_ENABLED` / `RATE_LIMIT_PER_MINUTE` | true / 600 | Per-IP sliding window over all `/api` traffic (429 + `Retry-After`) |
| `RATE_LIMIT_SEND_PER_MINUTE` | 30 | Per-user cap on manager message sends |
| `MAX_REQUEST_BODY_BYTES` | 10485760 | Bodies above this are rejected with 413 |
| `METRICS_TOKEN` | — (endpoint 404s) | Bearer token for Prometheus metrics at `/api/metrics` |
| `SENTRY_DSN` / `SENTRY_ENVIRONMENT` | — (disabled) | Optional error reporting; frontend uses `VITE_SENTRY_DSN` at build time |
| `SHUTDOWN_TIMEOUT_SECONDS` | 10 | Bound on worker drain during graceful shutdown |
| `DB_POOL_SIZE` / `DB_POOL_MAX_OVERFLOW` / `DB_POOL_TIMEOUT` | 5 / 5 / 30 | asyncpg pool limits |
| `PORT` | 8000 | Set automatically by Railway |

## Background workers (in-process asyncio tasks, advisory-locked)

| Worker | Flag | Every | Does |
|---|---|---|---|
| sync (`workers/sync_worker.py`) | `SYNC_ENABLED` | 5s | Backfills bot leads to contacts/deals, bot-driven stage moves, stage locks, unread counts, handover tasks, dialog list cache |
| outbox (`workers/outbox_worker.py`) | `OUTBOX_ENABLED` | 5s | POSTs queued manager messages to the n8n webhook, mirrors them into `knewit_messages` via `services/bot_bridge.py` (the only writer to `knewit_*`) |
| notify (`workers/notify_worker.py`) | `NOTIFICATIONS_ENABLED` | 60s | Overdue/due-soon task reminders + automations |
| realtime poller (`workers/realtime_poller.py`) | `REALTIME_ENABLED` | 2s | Polls `knewit_messages`/`knewit_events` by id, fans out on the event bus → SSE at `GET /api/stream` |

## n8n integration

- **Reads:** bot tables are read-only for the CRM (leads, messages, events).
- **Writes:** only through `backend/app/services/bot_bridge.py` — manager
  stage changes (`manual_stage_change` events) and mirrored outgoing
  messages (`direction='out'`, `message_type='manager'`). No triggers, no
  schema changes on `knewit_*`, ever.
- **Sending:** the CRM never stores provider keys. The outbox worker POSTs
  `{outbox_id, whatsapp_id, text}` to `N8N_SEND_WEBHOOK_URL`; n8n sends via
  its own provider and dedupes on `outbox_id`. See `docs/DECISIONS.md` (D6).

## Deploy (Railway, single container)

Full production guide: `docs/DEPLOY.md` (staging vs production, env table,
least-privilege `crm_app` role for the n8n database, domain/HTTPS,
first-run order, backups, rollback, CI/CD). Short version:

`railway.json` + `Dockerfile` (multi-stage: Node builds the SPA, Python
serves API + static; pinned bases; non-root user; entrypoint migrates
first, then serves with 1 worker (D26); healthcheck `GET /api/health`):

1. Deploy the repo, attach the n8n Postgres (or a new one) and reference its
   `DATABASE_URL` (production uses the `crm_app` role, see DEPLOY.md §3).
2. Set `ADMIN_EMAIL` / `ADMIN_PASSWORD`, `N8N_SEND_WEBHOOK_URL` /
   `N8N_WEBHOOK_SECRET`, generate a domain.
3. Verify with `scripts/smoke.sh` (see DEPLOY.md §7).

## Tests & lint

```bash
ruff check backend scripts && ruff format --check backend scripts
pytest -q                                   # needs local Postgres (docker compose up)
cd frontend && npm run typecheck && npm run lint && npm test && npm run build
```

Docs: `docs/PROGRESS.md` (step log), `docs/DECISIONS.md` (architecture),
`docs/db_schema.md` (bot tables reference).
