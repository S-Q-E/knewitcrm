# HUMAN_TODO — what a human must do (no secrets in the repo)

Everything below requires accounts you own. Nothing is committed to git except
placeholders. Deployment detail: `docs/tcs/RAILWAY_DEPLOY.md`.

## 0. Demo access (fill in before the presentation)

- [ ] Demo CRM URL: `https://______________________`
- [ ] Admin login: `________________` / stored in your password manager
- [ ] Demo bot: `@__________________` (NEW BotFather bot)
- [ ] n8n URL: `https://______________________`
- [ ] Check all four items the day before the demo.

## 1. Telegram bot

- [ ] Create a **new** bot in BotFather — never reuse the Knewit bot token.
- [ ] Put the token only into the n8n credential `Telegram account`.
- [ ] Rotate the token after the demo.

## 2. Railway (see `docs/tcs/RAILWAY_DEPLOY.md`)

- [ ] Create a separate project `tcs-demo` with Postgres + web service from the
  fork, branch `demo`. Never deploy into the original Knewit project.
- [ ] **Prepare the DB before the first boot** (schema → migrations → seed):
  Alembic 0015 backfills from `tcs_messages`, so a brand-new database needs
  `tests/fixtures/tcs_schema.sql` first. Commands are in the deploy guide §2.
- [ ] Enable the Postgres TCP proxy only for the one-time preparation and for
  seeding; disable it afterwards if n8n/CRM use private networking.
- [ ] Variables: `DATABASE_URL`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`,
  `DEFAULT_TIMEZONE=America/New_York`, `DEFAULT_CURRENCY=USD`,
  `COOKIE_SECURE=true`, `TRUSTED_PROXY_HOPS=1`,
  `N8N_SEND_WEBHOOK_URL`, `N8N_WEBHOOK_SECRET`.
  `DEMO_DB_CONFIRM` is for the seed command only — do not set it at runtime.
- [ ] Generate the HTTPS domain; healthcheck `GET /api/health` must return
  `{"ok": true}`.

## 3. n8n

- [ ] Check the n8n version; the demo expects the LangChain Agent (v3), the
  `n8n-nodes-base.postgresTool` and `@n8n/n8n-nodes-langchain.toolCode` nodes.
  Recommended: a current n8n (≥ 1.70). If a node is missing, build it from
  `docs/tcs/tools-spec.md`.
- [ ] Credentials in the UI (names referenced by the workflows):
  - `Telegram account` — the new demo bot token;
  - `Postgres account` — the demo Postgres (private host if the same Railway
    project, or the TCP-proxy host with SSL);
  - `OpenRouter account` — the LLM key (model `openai/gpt-4o-mini`).
- [ ] Import and attach credentials, in this order:
  1. `docs/n8n/tcs-send-message-telegram.workflow.json` (W-A, CRM → Telegram);
  2. `workflows/tcs_bot.json` (W-B, the bot);
  3. `workflows/tcs_reminders.json` (W-C, reminders).
- [ ] Create `n8n_processed_outbox` in the demo DB (SQL in
  `docs/n8n/README.md`) — needed by W-A only.
- [ ] Set `N8N_WEBHOOK_SECRET` in the n8n service env = CRM value.
- [ ] **MANUAL checks after import** (version-dependent; rebuild by hand from
  `docs/tcs/tools-spec.md` if needed):
  - W-B `Telegram Trigger` output shape — the normalizer reads
    `$json.message` and falls back to the item itself; verify with one message.
  - W-B `get_slots` (Code Tool): the `$('Load Booked Slots')` reference must
    resolve inside the tool; otherwise pass booked slots via the prompt.
  - W-B `search_units`, `book_viewing`, `handoff_to_human`: Postgres Tool nodes
    with `$fromAI` parameters.
  - W-B `Postgres Chat Memory`: first run creates `n8n_chat_histories`.
- [ ] Activate all three workflows; Telegram registers the webhook when the bot
  workflow is active. Send a test message.
- [ ] Test booking end-to-end: the CRM must show the deal on **Viewing
  scheduled** with a viewing time and a `trial_booked` event.
- [ ] Test the handoff: ask something out of scope → status Manager, urgent
  task, notification.
- [ ] Test the manager reply from the CRM: the message must reach Telegram and
  the bot must be paused.

## 4. CRM demo data

- [ ] Run `scripts/seed_tcs_demo.py` against the demo DB (with
  `DEMO_DB_CONFIRM`); wait ~15 seconds; verify 30 deals and one unanswered
  dialog.
- [ ] Create two manager users (Settings → Users) for the handoff scene.
- [ ] Before every rehearsal/demo: `--reset` + seed (see `DEMO_SCRIPT.md`).

## 5. Presentation

- [ ] Rehearse the 7-minute script; record a fallback video of the whole run.
- [ ] Replace the Estimated savings assumptions with real TCS numbers, or
  clearly say they are assumptions on stage.
- [ ] Keep `DEMO_SCRIPT.md` open in a second window (recovery table).

## 6. Before production (not part of the demo)

- [ ] Another channel (SMS or web chat) behind the same outbox contract.
- [ ] Legal review of the prompt (Fair Housing) and the consent text.
- [ ] Security audit of multi-tenancy and secrets handling.
- [ ] Address the P0 items in `docs/tcs/IMPROVEMENT_PLAN.md` (error alerts,
  heartbeat, outbox dead-letter, sync lag, migration 0015 guard).
- [ ] Do not merge the `demo` branch into `main` until these are done.
