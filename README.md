# TCS Leasing CRM — demo

Demo of an AI leasing assistant and a manager CRM for **TCS Property
Management** (Philadelphia, PA): a Telegram bot answers prospects 24/7,
books viewings, and the CRM shows every dialog, deal and handover.
All data is fictional; the UI permanently shows the **«DEMO — fictional
data»** banner. English interface, USD, `America/New_York`.

**What the demo proves**

1. The bot replies instantly at any hour and books a viewing.
2. Managers see every dialog and deal in the CRM and can take over.
3. No inquiry is left unanswered (the Unanswered tab + notifications).
4. Time and money saved, estimated from editable assumptions.

**Stack:** Python 3.12 + FastAPI + SQLAlchemy 2.0 (async) + Alembic on the
backend; React 18 + Vite + TypeScript + Tailwind on the frontend. The bot runs
in n8n and writes to the same Postgres (`tcs_leads`, `tcs_messages`,
`tcs_events`, `tcs_followups`, `tcs_units`); the CRM lives in the same database
in its own `crm_*` tables and never migrates bot tables.

## Quick start (local)

```bash
docker compose up -d                       # local Postgres 16 + bot fixtures
pip install -r requirements-dev.txt        # or use the existing .venv
alembic -c backend/alembic.ini upgrade head
DEMO_DB_CONFIRM=I_UNDERSTAND_THIS_IS_A_DEMO_DB \
  DATABASE_URL=postgresql://tcs:tcs@localhost:5432/tcs \
  python scripts/seed_tcs_demo.py
uvicorn backend.app.main:app --reload --port 8000
```

Open http://localhost:8000 and log in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`
(used once to bootstrap the first admin, then ignored). The entrypoint is
`backend/app/main.py:create_app()`.

Fresh demo database order matters: the bot schema must exist **before**
migrations (Alembic 0015 backfills from `tcs_messages`). On an empty database:

```bash
psql "$DATABASE_URL" -f tests/fixtures/tcs_schema.sql
alembic -c backend/alembic.ini upgrade head
python scripts/seed_tcs_demo.py            # with DEMO_DB_CONFIRM
```

Frontend dev (proxy to the API):

```bash
cd frontend && npm ci && npm run dev
```

## Demo data

`scripts/seed_tcs_demo.py` creates the **TCS Leasing** pipeline (single
default), 14 units in `tcs_units` (2 leased) and 30 fictional leads over
30 days: 121 messages, 12 viewings (6 done, 2 no-shows, 1 cancelled, 3 in the
next 2–5 days), one unanswered dialog (last incoming ~30 minutes ago, bot
live), two leads handed to a manager, ~40% of first messages outside
Mon–Fri 09:00–17:00 ET.

- Every demo row is marked `source = 'demo'`; telephones are `555-01xx`.
- The script refuses to run without
  `DEMO_DB_CONFIRM=I_UNDERSTAND_THIS_IS_A_DEMO_DB` and refuses if `tcs_leads`
  already contains `source = 'whatsapp'` (looks like a production bot DB).
- `--reset` deletes only `source = 'demo'` rows and their messages/events
  (never `TRUNCATE`). Re-run `--reset` + the seed right before a presentation.
- The legacy funnel «Продажи Knewit» stays in the database but is not default
  and is never opened during the demo (see `DEMO_SCRIPT.md`).

## Migrations

All CRM tables carry the `crm_` prefix and are created only via Alembic.
The version table is `crm_alembic_version`; `env.py` filters everything
except `crm_*`, so `tcs_*` and other n8n objects are never touched.

```bash
alembic -c backend/alembic.ini upgrade head
alembic -c backend/alembic.ini revision -m "what changed"  # edit upgrade()/downgrade()
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
| `DEFAULT_TIMEZONE` / `DEFAULT_CURRENCY` | America/New_York / USD | |
| `TRUSTED_PROXY_HOPS` | 1 | Trailing X-Forwarded-For entries added by our proxies (Railway = 1) |
| `SYNC_ENABLED` / `SYNC_INTERVAL_SECONDS` | true / 5 | Bot sync worker (leads → contacts/deals, locks, handover) |
| `OUTBOX_ENABLED` / `OUTBOX_INTERVAL_SECONDS` | true / 5 | Manager-message delivery worker |
| `NOTIFICATIONS_ENABLED` | true | Task reminders + automations worker (60s cycle) |
| `REALTIME_ENABLED` | true | Bot-table poller feeding SSE (2s cycle) |
| `N8N_SEND_WEBHOOK_URL` / `N8N_WEBHOOK_SECRET` | — | n8n webhook that sends Telegram messages (`X-CRM-Secret` header) |
| `ALLOWED_ORIGINS` | empty (same-origin only) | Extra origins allowed for CORS (credentials on) |
| `RATE_LIMIT_ENABLED` / `RATE_LIMIT_PER_MINUTE` | true / 600 | Per-IP sliding window over all `/api` traffic (429 + `Retry-After`) |
| `RATE_LIMIT_SEND_PER_MINUTE` | 30 | Per-user cap on manager message sends |
| `MAX_REQUEST_BODY_BYTES` | 10485760 | Bodies above this are rejected with 413 |
| `METRICS_TOKEN` | — (endpoint 404s) | Bearer token for Prometheus metrics at `/api/metrics` |
| `SENTRY_DSN` / `SENTRY_ENVIRONMENT` | — (disabled) | Optional error reporting |
| `SHUTDOWN_TIMEOUT_SECONDS` | 10 | Bound on worker drain during graceful shutdown |
| `DB_POOL_SIZE` / `DB_POOL_MAX_OVERFLOW` / `DB_POOL_TIMEOUT` | 5 / 5 / 30 | asyncpg pool limits |
| `DEMO_DB_CONFIRM` | — | Required by `scripts/seed_tcs_demo.py`; never set it on a production database |
| `PORT` | 8000 | Set automatically by Railway |

## Background workers (in-process asyncio tasks, advisory-locked)

| Worker | Flag | Every | Does |
|---|---|---|---|
| sync (`workers/sync_worker.py`) | `SYNC_ENABLED` | 5s | Backfills bot leads to contacts/deals, bot-driven stage moves, stage locks, unread counts, handover tasks, dialog list cache |
| outbox (`workers/outbox_worker.py`) | `OUTBOX_ENABLED` | 5s | POSTs queued manager messages to the n8n webhook, mirrors them into `tcs_messages` via `services/bot_bridge.py` (the only writer to `tcs_*`) |
| notify (`workers/notify_worker.py`) | `NOTIFICATIONS_ENABLED` | 60s | Overdue/due-soon task reminders + automations |
| realtime poller (`workers/realtime_poller.py`) | `REALTIME_ENABLED` | 2s | Polls `tcs_messages`/`tcs_events` by id, fans out on the event bus → SSE at `GET /api/stream` |

## n8n integration (Telegram)

| File | Role |
|---|---|
| `workflows/tcs_bot.json` | Telegram bot: normalize → pause check → log → agent with four tools → reply → state/events |
| `workflows/tcs_reminders.json` | Viewing reminders every 15 minutes (next 24 h, `reminder_sent`) |
| `docs/n8n/tcs-send-message-telegram.workflow.json` | CRM outbox → Telegram (`{outbox_id, whatsapp_id, text}` + `X-CRM-Secret`, dedupe, 502 on failure) |

Generated by `scripts/build_tcs_workflows.py`, validated by
`scripts/validate_workflow.py`; do not hand-edit the JSON. Tool SQL/JS:
`docs/tcs/tools-spec.md`; the system prompt: `docs/tcs/bot-prompt.md`.
Pause state is `crm_conversation_state.bot_paused` (a manager reply in the CRM
pauses the bot automatically). Sending from the CRM never stores provider
keys: the outbox worker POSTs to `N8N_SEND_WEBHOOK_URL`, and n8n sends and
dedupes on `outbox_id`.

## Deploy (Railway)

Follow **`docs/tcs/RAILWAY_DEPLOY.md`** (separate demo project, schema-first
database preparation, seed, env vars, n8n wiring, rehearsal checklist).
`railway.json` + `Dockerfile` build the SPA and serve API + static from one
container (migrate-on-boot, 1 worker, healthcheck `GET /api/health`).

## Tests & lint

```bash
ruff check backend scripts && ruff format --check backend scripts
pytest -q                                   # needs local Postgres (docker compose up)
cd frontend && npm run typecheck && npm run lint && npm test && npm run build
python scripts/validate_workflow.py         # generated n8n workflows
```

## Docs

- `DEMO_SCRIPT.md` — 7-minute scenario and the pre-demo checklist.
- `HUMAN_TODO.md` — what a human must do (BotFather, Railway, n8n, legal).
- `CHANGES.md` — everything changed for the demo.
- `docs/DECISIONS.md` — architecture decisions (D41–D42 cover the demo).
- `docs/db_schema.md` — `tcs_*` reference.
- `docs/tcs/` — bot prompt, tool specs, improvement plan, Railway deploy guide.
- `docs/PROGRESS.md` — step log.
