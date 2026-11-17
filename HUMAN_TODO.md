# HUMAN_TODO — what a human must do (no secrets in the repo)

Phase 5 expands this list; Phase 4 items are marked [P4].

## n8n — demo bot + workflows

- [P4] **New Telegram bot in BotFather.** Use a NEW bot, never the Knewit bot
  token. Put the token only into the n8n credential (see below).
- [P4] **n8n credentials in the UI** (names as referenced by the workflows):
  - `Telegram account` — the new demo bot token;
  - `Postgres account` — the demo Postgres (same DB as the CRM);
  - `OpenRouter account` — the LLM key (the model stays `openai/gpt-4o-mini`).
  Nothing is committed to git; tokens live only in n8n.
- [P4] **Import the workflows** in this order:
  1. `docs/n8n/tcs-send-message-telegram.workflow.json` (W-A, CRM to Telegram);
  2. `workflows/tcs_bot.json` (W-B, the Telegram bot);
  3. `workflows/tcs_reminders.json` (W-C, viewing reminders).
  After each import, attach the credentials and save.
- [P4] **MANUAL checks after import** (version-dependent; rebuild by hand from
  `docs/tcs/tools-spec.md` if the node is missing or looks different):
  - W-B `Telegram Trigger` output shape: the workflow reads
    `$json.message` (falls back to the item itself) — verify one test message.
  - W-B `get_slots` (Code Tool): the `$('Load Booked Slots')` reference must
    resolve inside the tool; if not, pass the booked slots through the prompt
    context instead (see the note in tools-spec.md).
  - W-B `search_units`, `book_viewing`, `handoff_to_human`: Postgres Tool nodes
    (`n8n-nodes-base.postgresTool`) with `$fromAI` parameters. If your n8n does
    not offer the Postgres Tool node, build the same query as a tool manually
    from `docs/tcs/tools-spec.md`.
  - W-B `Postgres Chat Memory`: first run creates `n8n_chat_histories`; check
    the credential points at the demo DB.
- [P4] **Env in n8n:** `N8N_WEBHOOK_SECRET` must equal the CRM value. In the
  CRM set `N8N_SEND_WEBHOOK_URL=https://<n8n-host>/webhook/crm-send-message`.
- [P4] **Dedupe table** for W-A: run the SQL from `docs/n8n/README.md`
  (`n8n_processed_outbox`) once on the demo DB.
- [P4] **Activate** all three workflows. Telegram registers the webhook when
  the bot workflow is activated; write a test message to the bot.
- [P4] **Test the handoff path:** ask the bot something out of scope
  (e.g. “Do you handle maintenance?”) and confirm in the CRM: status becomes
  Manager, an urgent task and a notification appear.

## Railway (demo project)

- [P5] Create a NEW Railway project with a separate Postgres and a service from
  the fork of this repo (branch `demo`). Never deploy into the original project.
- [P5] Variables: `DATABASE_URL` (demo DB), `ADMIN_EMAIL`, `ADMIN_PASSWORD`,
  `DEFAULT_TIMEZONE=America/New_York`, `DEFAULT_CURRENCY=USD`,
  `COOKIE_SECURE=true`, `N8N_SEND_WEBHOOK_URL`, `N8N_WEBHOOK_SECRET`,
  `DEMO_DB_CONFIRM=I_UNDERSTAND_THIS_IS_A_DEMO_DB` (for the seed run).
- [P5] Fresh demo DB order (the current Alembic history expects the bot schema
  before migrations): apply `tests/fixtures/tcs_schema.sql`, then
  `alembic upgrade head`, then `scripts/seed_tcs_demo.py`. Migration 0015
  backfills from `tcs_messages` without an existence guard — revisit with the
  team before the deploy if you want a different order.

## CRM demo data

- [P5] Run `scripts/seed_tcs_demo.py` against the demo DB (with
  `DEMO_DB_CONFIRM`), wait for the sync worker, verify 30 deals and one
  unanswered dialog.
- [P5] Create two manager users in CRM Settings and one admin for the demo.

## Legal / production notes

- [P5] Rehearse the 7-minute script, record a fallback video.
- [P5] Replace the ROI assumptions with real TCS numbers.
- [P5] Before production: another channel (SMS or web chat), legal review of the
  prompt (Fair Housing) and the consent text, security audit of multi-tenancy.
