# DEMO SCRIPT — TCS Leasing CRM (7 minutes)

Presenter notes are in Russian, everything said to the client is in English.
All data is fictional; the «DEMO — fictional data» banner is always visible.
Do not open the pipeline selector: the legacy funnel «Продажи Knewit» stays in
the database but is not part of the demo.

## Before the demo (30 minutes)

- [ ] `scripts/seed_tcs_demo.py --reset` then the seed again (with
      `DEMO_DB_CONFIRM`), so the unanswered dialog is ~30 minutes old and the
      three viewings are in the next 2–5 days.
- [ ] Wait 15 seconds for the sync worker; check: 30 deals on the TCS board,
      exactly one dialog in **Dialogs → Unanswered**.
- [ ] Send one message to the demo Telegram bot and confirm the reply; confirm
      the new dialog appears in the CRM within ~5 seconds.
- [ ] Reply once from the CRM dialog and confirm the message reaches Telegram
      (the bot is paused automatically after a manual reply).
- [ ] Confirm the **Viewing scheduled** deal from the seed shows a viewing time.
- [ ] Close extra browser tabs; set the CRM theme to light; zoom 110–125%.
- [ ] Have the fallback video ready (recorded run of the same scenario).
- [ ] Keep `HUMAN_TODO.md` open in a second window: it has the recovery steps.

## Scenario

### 0:00 — Intro (60 s)

Presenter (RU cue): «TCS управляет квартирами в Филадельфии. Клиенты пишут
вечером и в выходные — а офис отвечает утром. Часть обращений теряется.»

Spoken (EN, short):
> “Prospects message property managers at night, on weekends, and while your
> team is showing apartments. The first reply often comes hours later — and
> some inquiries never get an answer at all. This is a working demo of an AI
> leasing assistant that answers in seconds, books viewings, and puts every
> conversation in a CRM your team can take over at any moment. All data here is
> fictional — it is a demo environment.”

### 1:00 — Telegram, “at night” (120 s)

Open Telegram on the phone (or Telegram Desktop) and type:

1. `Hi, any 2-bedroom under $2,200?`
   - Expected: a short friendly reply that introduces the AI assistant and
     asks about move-in timing (never a price invented from memory).
2. `Moving in around January 1st. Do you have anything at Demo Residences A?`
   - Expected: units with real prices from the catalog (e.g. a 2BR around
     $2,250–$2,600) and an offer to schedule a viewing.
3. `Yes, let's see it. Evenings work best.`
   - Expected: the bot offers up to three slots (30 minutes, weekdays
     09:00–17:00 New York time).
4. Pick the first slot, e.g. `The first one works.`
   - Expected: the bot confirms the date, time and address.

Presenter (EN):
> “It is 11 pm. Nobody from the office is working — and the assistant has just
> collected the budget, the move-in date, and booked a viewing.”

If the bot offers a different unit, go with it: the point is the booked
viewing, not a specific apartment.

### 3:00 — CRM: the deal is already there (60 s)

Switch to the CRM (Deals board, TCS Leasing pipeline).

- The new deal sits in **Viewing scheduled** (or **Unit matched** if the
  bot is still asking — refresh once).
- Open the deal: the sidebar shows **Viewing** with the selected date/time,
  and the bot block shows **Unit of interest**, **Move-in & budget**,
  **Bedrooms**, **Viewing preference**.
- Point at the DEMO banner and say: “Every card here is fictional.”

Presenter (EN):
> “No copy-paste, no manual entry. The conversation, the lead and the viewing
> are already in the pipeline — while the office was closed.”

### 4:00 — Handoff to a human (60 s)

Back in Telegram, ask something out of scope:

`Do you handle maintenance requests in the building?`

- Expected: “The office team will help with that…” and a handoff
  (`status = Manager`, `transferred_to_manager` event).

Switch to the CRM:

- The bell shows a notification; a new **urgent task** is assigned.
- Open **Dialogs**, open that dialog, type a reply, send.
- Expected: the message appears in Telegram; the dialog shows **Pause bot**
  as active (a manual reply pauses the bot automatically).

Presenter (EN):
> “The assistant knows what it should not answer. It hands the conversation to
> a manager — with a notification and an urgent task — and stays out of the way
> after the manager replies.”

### 5:00 — Nothing is left unanswered (40 s)

Open **Dialogs → Unanswered**.

- Exactly one dialog is there: last incoming message ~30 minutes old, bot
  never answered, not paused.
- The notification bell and the counter show it.

Presenter (EN):
> “Every unanswered conversation is visible in one place, with a timer. Nothing
> silently disappears.”

### 6:00 — Estimated savings (30 s)

Open **Analytics**, scroll to **Estimated savings**.

- “Leasing rep time saved”, “Money saved (estimate)”, “Bot responds in”,
  “Times faster than a rep”.
- Change **Hourly cost** from 25 to 35 and **Minutes per inquiry** from 8 to 10:
  the numbers recalculate instantly.
- Read the caption: “Assumption: replace with TCS numbers” and
  “Estimate based on editable assumptions, not measured results”.

Presenter (EN):
> “This is an estimate, not a measured result. Replace our assumptions with
> your numbers and the model recalculates. The after-hours KPI above is real
> for this demo data: about 40% of first messages arrived outside business
> hours.”

### 6:30 — Closing (30 s)

Presenter (EN):
> “One Telegram bot, the same CRM, and a full audit trail. In production we
> connect your real listings, your rules and your team — and the AI only says
> what your data allows it to say.”

## Recovery if something breaks

| Problem | What to do |
|---|---|
| Bot does not answer | Check n8n: the workflow is active, the Telegram credential is attached; check the pause flag in the dialog. If it is still broken, switch to the fallback video and continue from the CRM. |
| No new deal in the CRM | Wait 5–10 seconds (sync cycle), refresh. Check `sync_worker.last_synced_at` in Settings. |
| Viewing time missing | The booking tool may have returned `slot_taken`; pick another slot in Telegram. |
| CRM reply does not arrive in Telegram | Check n8n W-A (`tcs-send-message-telegram`) is active and `N8N_SEND_WEBHOOK_URL`/`N8N_WEBHOOK_SECRET` match. If it is down, show the paused-bot state and move to Analytics. |
| Unanswered tab is empty or has two dialogs | Re-run `--reset` + seed (15 s), or explain using the pre-seeded deal card instead. |
| Everything fails | Play the fallback video and narrate it; the CRM tabs remain available for questions. |
