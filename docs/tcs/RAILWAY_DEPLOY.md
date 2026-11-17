# Deploy the TCS demo to Railway

One-time setup for a **separate demo project** with its own database. The
original repository/project is never touched; deploy only branch `demo` from
the fork. Everything here assumes two Railway things:

1. a new project `tcs-demo` with **Postgres** and the **CRM web service**;
2. your existing **n8n** service (its own project or the same one).

All data is fictional. Never point this project at a production database.

## 0. Prerequisites

- GitHub fork with branch `demo` (contains `Dockerfile`, `railway.json`).
- A NEW Telegram bot from BotFather (never the Knewit bot token).
- Local tools for the one-time database preparation: `psql`, Python + venv
  with `requirements-dev.txt` installed (the repo's `.venv` works).
- Railway account with permission to create projects.

## 1. Create the project and the database

1. Railway → **New Project → Empty Project** → name `tcs-demo`.
2. **+ Create → Database → PostgreSQL** (Postgres 16 is fine).
3. Railway injects `DATABASE_URL` for services in the same project using the
   private network. That is what the CRM will use at runtime.
4. For the **one-time preparation** you need a public connection string:
   - Postgres service → **Settings → Networking → TCP Proxy → Enable**;
   - copy the proxy host/port and the credentials from **Variables**
     (`PGUSER`, `PGPASSWORD`, `PGDATABASE`).
   - Public URL form:
     `postgresql://<PGUSER>:<PGPASSWORD>@<proxy-host>:<proxy-port>/<PGDATABASE>?sslmode=require`
5. Keep the TCP proxy only while preparing/seeding; you can disable it after
   the demo DB is ready (n8n and the CRM use private networking).

## 2. Prepare the demo database (one-time, from your machine)

The image runs `alembic upgrade head` on every boot. Migration `0015`
backfills from `tcs_messages` **without an existence guard**, so on an empty
database the bot schema must exist first. Run exactly this order:

```bash
cd tcs_demo
export RAILWAY_DB='postgresql://...:...@...:..../railway?sslmode=require'

# 1) bot schema (tcs_leads, tcs_messages, tcs_events, tcs_followups, ...)
psql "$RAILWAY_DB" -f tests/fixtures/tcs_schema.sql

# 2) CRM tables
DATABASE_URL="$RAILWAY_DB" alembic -c backend/alembic.ini upgrade head

# 3) TCS funnel + fictional demo data (guardrails apply)
DEMO_DB_CONFIRM=I_UNDERSTAND_THIS_IS_A_DEMO_DB \
DATABASE_URL="$RAILWAY_DB" python scripts/seed_tcs_demo.py

# 4) n8n dedupe table for CRM → Telegram sends (SQL from docs/n8n/README.md,
#    section «Дедупликация»)
psql "$RAILWAY_DB" -c "CREATE TABLE IF NOT EXISTS n8n_processed_outbox (
  outbox_id uuid PRIMARY KEY,
  provider_message_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);"

# 5) sanity checks
psql "$RAILWAY_DB" -c "SELECT count(*) AS demo_leads FROM tcs_leads WHERE source='demo';"
psql "$RAILWAY_DB" -c "SELECT count(*) AS units FROM tcs_units;"
psql "$RAILWAY_DB" -c "SELECT name, is_default FROM crm_pipelines ORDER BY name;"
```

Expected: 30 demo leads, 14 units, `TCS Leasing` is the only default pipeline.
On the live CRM (step 5) you will additionally see 30 deals and one unanswered
dialog after the sync worker runs.

> Alternative: `railway run` inside the web service executes the command
> locally with the service variables injected. The seed script exists in the
> image (`scripts/seed_tcs_demo.py`), so
> `railway run env DEMO_DB_CONFIRM=... python scripts/seed_tcs_demo.py` also
> works after the first successful boot. The manual order above is simpler for
> the first deployment.

## 3. Create the CRM web service

1. **+ Create → GitHub Repo** → select the fork → branch `demo`.
2. Build: `Dockerfile` (Railway picks up `railway.json`). Root directory:
   repository root.
3. Generate a domain (**Settings → Networking → Generate Domain**).
   HTTPS is terminated by Railway; keep `COOKIE_SECURE=true`.
4. Variables (service → **Variables**):

| Variable | Value |
|---|---|
| `DATABASE_URL` | reference from the Postgres service (`${{Postgres.DATABASE_URL}}`) — private network |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | first admin; password ≥ 10 chars; used only once |
| `DEFAULT_TIMEZONE` | `America/New_York` |
| `DEFAULT_CURRENCY` | `USD` |
| `COOKIE_SECURE` | `true` |
| `TRUSTED_PROXY_HOPS` | `1` |
| `N8N_SEND_WEBHOOK_URL` | `https://<your-n8n-host>/webhook/crm-send-message` |
| `N8N_WEBHOOK_SECRET` | the same value as in n8n (`N8N_WEBHOOK_SECRET`) |
| `N8N_...` others | leave defaults (`SYNC_ENABLED`, `OUTBOX_ENABLED`, `NOTIFICATIONS_ENABLED`, `REALTIME_ENABLED` = true) |
| `METRICS_TOKEN` | optional, for `/api/metrics` |
| `DEMO_DB_CONFIRM` | **do not set at runtime** — only for the one-time seed command |

5. Deploy. The entrypoint runs migrations, then serves one uvicorn worker;
   healthcheck is `GET /api/health`.

## 4. First boot verification

```bash
curl -s https://<crm-domain>/api/health          # {"ok": true}
curl -s -o /dev/null -w '%{http_code}\n' https://<crm-domain>/login   # 200
```

- Open the CRM, log in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`.
- Board shows the **TCS Leasing** pipeline with 30 deals (allow ~5 s).
- **Dialogs → Unanswered** shows exactly one dialog.
- Analytics → **Estimated savings** renders and recalculates.

If the service crashes on boot with `relation "tcs_messages" does not exist`,
the database preparation in step 2 was skipped — run it and redeploy.

## 5. Connect n8n (Railway)

n8n must reach the demo database:

- **n8n and Postgres in the same Railway project:** use the private host
  (`postgres.railway.internal` / `${{Postgres.PGHOST}}`), port 5432, database
  and user/password from the Postgres variables; SSL is not required.
- **n8n in another project:** enable the Postgres **TCP Proxy**, use the public
  host/port, and enable SSL in the n8n credential (`sslmode=require`).

Then:

1. Create n8n credentials: `Postgres account` (demo DB), `Telegram account`
   (new demo bot), `OpenRouter account` (LLM key).
2. Import, in this order:
   `docs/n8n/tcs-send-message-telegram.workflow.json`,
   `workflows/tcs_bot.json`, `workflows/tcs_reminders.json`.
   Attach credentials; save each workflow.
3. Check the version-dependent nodes (see `HUMAN_TODO.md` → MANUAL):
   Telegram Trigger output shape, `postgresTool` nodes for
   `search_units`/`book_viewing`/`handoff_to_human`, Code Tool `get_slots`.
   If a node type is missing, build it from `docs/tcs/tools-spec.md`.
4. Set `N8N_WEBHOOK_SECRET` in the n8n service variables (same as the CRM).
5. Activate all three workflows. Send a message to the bot; the CRM dialog
   must appear within ~5 seconds.
6. Test the manager reply: send from a CRM dialog, the message must arrive in
   Telegram. If not, check W-A is active and the secret matches.

## 6. Before the presentation

```bash
# refresh the demo slice (unanswered dialog becomes ~30 min old again)
DEMO_DB_CONFIRM=I_UNDERSTAND_THIS_IS_A_DEMO_DB \
DATABASE_URL='<private or public URL>' python scripts/seed_tcs_demo.py --reset
DEMO_DB_CONFIRM=I_UNDERSTAND_THIS_IS_A_DEMO_DB \
DATABASE_URL='<private or public URL>' python scripts/seed_tcs_demo.py
```

Wait 15 seconds (sync worker), then follow `DEMO_SCRIPT.md` → «Before the demo».

## 7. Operations and rollback

- **Backups:** Railway Postgres → Backups. The demo data is disposable; the
  seed recreates the whole slice.
- **Rollback:** Railway → Deployments → Redeploy a previous one. Database
  downgrades are not needed: the demo DB can be recreated and re-seeded.
- **Costs:** one Postgres + one small web service; stop the service after the
  demo if it is not needed.
- **Do not merge `demo` into `main`** and do not deploy this workflow from the
  original Knewit project.
- **Security:** rotate the demo bot token, the n8n secret and the admin
  password after the demo; disable the Postgres TCP proxy when not seeding.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Boot fails on `0015_dialogs_list` (`tcs_messages` missing) | Apply `tests/fixtures/tcs_schema.sql` before migrations (step 2). |
| Login loops back to `/login` | `COOKIE_SECURE=true` over plain HTTP; use the generated HTTPS domain or set `false` locally. |
| 401 on every n8n webhook call | `N8N_WEBHOOK_SECRET` differs between the CRM and n8n env. |
| Bot silent | Workflow inactive, Telegram credential wrong, or the dialog is paused (`crm_conversation_state.bot_paused`). |
| No deals after seeding | `SYNC_ENABLED=false` or the service cannot reach the DB; check logs and `/api/ready`. |
| CRM send never arrives | W-A inactive, `N8N_SEND_WEBHOOK_URL` wrong, or n8n cannot reach the CRM URL from inside Railway. |
