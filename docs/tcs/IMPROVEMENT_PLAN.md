# TCS demo — improvement plan (post-demo / production)

Source of ideas: the reference workflow
`docs/tcs/reference-whatsapp-tickets.workflow.json` (WhatsApp + maintenance
tickets + multimodal intake) and the Phase 2–5 notes. Nothing here is part of
the current demo scope; it is the backlog after the client presentation.

Priority: P0 = before any pilot with real clients; P1 = first month of a pilot;
P2 = product growth.

## P0 — reliability and failure detection

- [ ] **n8n Error Trigger → admin alert.** One error workflow for all three
  TCS workflows: send the workflow name, failing node, execution id and error
  message to the admin in Telegram (same demo bot or a separate ops bot).
  The reference workflow already shows this pattern with WhatsApp; port it to
  Telegram. Reason: right now a broken bot fails silently for the client.
- [ ] **Heartbeat / dead-man switch.** A tiny workflow every 15 minutes writes
  a timestamp to `crm_settings` (e.g. `n8n_heartbeat`); the CRM shows a banner
  when the bot has not checked in for 30+ minutes. Covers paused/deleted
  workflows and webhook problems.
- [ ] **Outbox dead-letter alert.** CRM already marks a send `failed`; add a
  notification to managers when a message stays failed for 10 minutes.
- [ ] **Sync worker lag alert.** If `sync_worker.last_synced_at` is older than
  N minutes, notify the admin: the CRM is silently showing stale data.
- [ ] **Fresh-DB migration order.** Add the existence guard to Alembic 0015
  (like 0009) or document/applify the schema-first order in the deploy.

## P1 — channel and intake coverage

- [ ] **Multimodal intake** (from the reference workflow): photos → vision
  description, voice notes → transcription, video → placeholder + handoff.
  Costs and privacy must be agreed before enabling.
- [ ] **Maintenance / tenant flow** (from the reference workflow): tenants ask
  for repairs, the bot triages category and urgency, creates a ticket, escalates
  emergencies to the on-call person. Requires ticket tables, SLA timers and a
  second prompt branch (the reference `pm_*` schema is a good starting point,
  but it must be mapped onto `tcs_*` + CRM, not a parallel backend).
- [ ] **Knowledge base (RAG)** for policies, FAQ and building rules; answers
  must stay behind the “use only tool data” rule and Fair Housing guardrails.
- [ ] **Extra channels** (SMS, web chat) behind the same `{outbox_id,
  whatsapp_id, text}` contract; the CRM and `tcs_*` stay unchanged.

## P1 — manager experience

- [ ] Manager lead card on handoff (from the reference workflow): unit, budget,
  move-in, urgency, transcript summary — delivered as a Telegram card to the
  leasing manager, in addition to the CRM notification.
- [ ] SLA timers for unanswered dialogs (escalate after 15/60 minutes), visible
  in the Unanswered tab.
- [ ] Follow-up automation for the Follow-up stage (the bot's `tcs_followups`
  table exists; no worker yet).

## P2 — demo/ops maturity

- [ ] Workflow contract tests in CI: import JSON into a disposable n8n
  (docker) and assert nodes/credentials references; currently only structural
  validation runs.
- [ ] E2E test with a dedicated test bot: send a message, assert lead + deal +
  event rows.
- [ ] Replace the Estimated savings assumptions with real TCS numbers and
  label the source/period.
- [ ] Secrets management: one credential set per environment, rotation policy,
  no `$env` reliance in expressions where a credential is possible.
- [ ] Data retention and PII policy for chat transcripts; consent text review.
- [ ] Legal review of the prompt (Fair Housing) and the demo disclaimer.
