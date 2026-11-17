"""Build the TCS demo n8n workflows.

Templates are the original Knewit workflows in docs/n8n/; node parameters are
cloned from them. Tool SQL/JS comes from docs/tcs/tools-spec.md, the system
prompt from docs/tcs/bot-prompt.md.

Outputs:
  docs/n8n/tcs-send-message-telegram.workflow.json   (W-A)
  workflows/tcs_bot.json                             (W-B)
  workflows/tcs_reminders.json                       (W-C)

Run: .venv/bin/python scripts/build_tcs_workflows.py
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
N8N_DIR = ROOT / "docs" / "n8n"
TCS_DOCS = ROOT / "docs" / "tcs"
WORKFLOWS = ROOT / "workflows"

SEND_WA = N8N_DIR / "crm-send-message.workflow.json"
BOT_ORIGINAL = N8N_DIR / "knewit-whatsapp-v2.json"
TOOLS_SPEC = TCS_DOCS / "tools-spec.md"
BOT_PROMPT = TCS_DOCS / "bot-prompt.md"

OUT_SEND = N8N_DIR / "tcs-send-message-telegram.workflow.json"
OUT_BOT = WORKFLOWS / "tcs_bot.json"
OUT_REMINDERS = WORKFLOWS / "tcs_reminders.json"

TELEGRAM_CREDS = {"telegramApi": {"name": "Telegram account"}}
POSTGRES_CREDS = {"postgres": {"name": "Postgres account"}}
TOOLS_MIN = ("search_units", "get_slots", "book_viewing", "handoff_to_human")

TCS_STAGES = [
    "NEW_INQUIRY",
    "QUALIFYING",
    "UNIT_MATCHED",
    "VIEWING_SCHEDULED",
    "VIEWING_CONFIRMED",
    "VIEWING_DONE",
    "APPLICATION_SENT",
    "FOLLOW_UP",
]
TCS_ACTIONS = [
    "none",
    "update_data",
    "transfer_to_manager",
    "set_followup",
    "mark_lost",
    "mark_won",
]


def nid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "tcs-demo:" + name))


def node(
    name: str,
    type_: str,
    type_version: float,
    position: list[int],
    parameters: dict,
    **extra: Any,
) -> dict:
    data = {
        "parameters": parameters,
        "id": nid(name),
        "name": name,
        "type": type_,
        "typeVersion": type_version,
        "position": position,
    }
    data.update(extra)
    return data


def link(
    connections: dict,
    source: str,
    targets: list[str],
    output: int = 0,
    kind: str = "main",
    target_type: str | None = None,
) -> None:
    branches = connections.setdefault(source, {}).setdefault(kind, [])
    while len(branches) <= output:
        branches.append([])
    for target in targets:
        branches[output].append({"node": target, "type": target_type or kind, "index": 0})


def read_spec_block(heading: str, lang: str) -> str:
    """Extract the first ```<lang> block under a '## ...' heading."""
    text = TOOLS_SPEC.read_text(encoding="utf-8")
    start = text.index(heading)
    rest = text[start:]
    match = re.search(r"```" + lang + r"\n(.*?)```", rest, re.S)
    if not match:
        raise SystemExit(f"no {lang} block under {heading!r} in {TOOLS_SPEC}")
    return match.group(1).rstrip() + "\n"


def sticky(name: str, content: str, position: list[int], **extra: Any) -> dict:
    params = {"content": content, "height": 320, "width": 460, "color": 4}
    params.update(extra)
    return node(name, "n8n-nodes-base.stickyNote", 1, position, params)


def workflow(name: str, nodes: list[dict], connections: dict) -> dict:
    return {
        "name": name,
        "nodes": nodes,
        "connections": connections,
        "active": False,
        "settings": {"executionOrder": "v1"},
        "staticData": None,
        "pinData": {},
        "meta": {"templateCredsSetupCompleted": False},
    }


# ---------------------------------------------------------------------- W-A


def build_send_message() -> dict:
    src = json.loads(SEND_WA.read_text(encoding="utf-8"))
    nodes = [n for n in src["nodes"] if n["name"] not in ("Send WhatsApp Message", "Send OK?")]
    for n in nodes:
        if n["name"] == "Sticky Note":
            n["parameters"]["content"] = (
                "## TCS Send Message (Telegram)\n"
                "1. Import: Workflows -> Import from file. Attach credentials in the UI: "
                "`Postgres account`, `Telegram account` (the NEW demo bot, not the Knewit bot).\n"
                "2. `n8n_processed_outbox` comes from docs/n8n/README.md.\n"
                "3. Env `N8N_WEBHOOK_SECRET` in n8n = CRM `N8N_WEBHOOK_SECRET`.\n"
                "4. Telegram has no `success` field: success output -> Mark Sent -> Respond OK; "
                "error output -> Respond Error (502). Dedupe row is written only after a successful send.\n"
                "5. Activate; webhook URL https://<n8n>/webhook/crm-send-message -> CRM `N8N_SEND_WEBHOOK_URL`."
            )
    nodes.append(
        node(
            "Send Telegram Message",
            "n8n-nodes-base.telegram",
            1.2,
            [272, 368],
            {
                "chatId": "={{ String($('CRM Send Webhook').item.json.body.whatsapp_id)"
                ".replace(/^tg:/, '') }}",
                "text": "={{ $('CRM Send Webhook').item.json.body.text }}",
                "additionalFields": {"appendAttribution": False},
            },
            credentials=TELEGRAM_CREDS,
            onError="continueErrorOutput",
        )
    )
    src["nodes"] = nodes

    conns = src["connections"]
    conns.pop("Send WhatsApp Message", None)
    conns.pop("Send OK?", None)
    conns["Is Duplicate"]["main"][1] = [
        {"node": "Send Telegram Message", "type": "main", "index": 0}
    ]
    conns["Send Telegram Message"] = {
        "main": [
            [{"node": "Mark Sent", "type": "main", "index": 0}],
            [{"node": "Respond Error", "type": "main", "index": 0}],
        ]
    }
    src["name"] = "TCS Send Message (Telegram)"
    return src


# ---------------------------------------------------------------------- W-B


def _knewit_nodes() -> dict[str, dict]:
    data = json.loads(BOT_ORIGINAL.read_text(encoding="utf-8"))
    return {n["name"]: n for n in data["nodes"]}


def _parser_schema() -> str:
    schema = {
        "type": "object",
        "properties": {
            "reply": {"type": "string"},
            "new_stage": {"type": "string", "enum": TCS_STAGES},
            "action": {"type": "string", "enum": TCS_ACTIONS},
            "collected_data": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string"},
                    "goal": {"type": "string"},
                    "preferred_format": {"type": "string"},
                    "preferred_time": {"type": "string"},
                    "last_objection": {"type": "string"},
                    "lead_data": {
                        "type": "object",
                        "properties": {
                            "budget_usd": {"type": "number"},
                            "unit": {"type": "string"},
                            "pets": {"type": "string"},
                        },
                    },
                },
            },
            "confidence": {"type": "number"},
            "internal_note": {"type": "string"},
        },
        "required": ["reply", "new_stage", "action", "collected_data", "confidence"],
    }
    return json.dumps(schema, ensure_ascii=False)


def _validate_js() -> str:
    return """
const allowedStages = ["NEW_INQUIRY","QUALIFYING","UNIT_MATCHED","VIEWING_SCHEDULED",
"VIEWING_CONFIRMED","VIEWING_DONE","APPLICATION_SENT","FOLLOW_UP"];
const allowedActions = ["none","update_data","transfer_to_manager","set_followup","mark_lost","mark_won"];

const agentOutput = ($json.output && typeof $json.output === 'object') ? $json.output : {};
const lead = $('Upsert & Load Lead State').item.json;
const startedAt = $('Build Agent Context').item.json.started_at;
const responseTimeMs = startedAt ? (Date.now() - new Date(startedAt).getTime()) : null;

let reply = (typeof agentOutput.reply === 'string' && agentOutput.reply.trim().length > 0)
  ? agentOutput.reply.trim()
  : "Sorry, I'm having trouble right now. Our team will message you shortly.";

let newStage = allowedStages.includes(agentOutput.new_stage) ? agentOutput.new_stage : lead.current_stage;
let action = allowedActions.includes(agentOutput.action) ? agentOutput.action : 'none';
const collected = (agentOutput.collected_data && typeof agentOutput.collected_data === 'object') ? agentOutput.collected_data : {};
const collectedLeadData = (collected.lead_data && typeof collected.lead_data === 'object') ? collected.lead_data : {};
const confidence = (typeof agentOutput.confidence === 'number') ? agentOutput.confidence : 0.5;
const internalNote = (typeof agentOutput.internal_note === 'string') ? agentOutput.internal_note : '';

let status = lead.status;
if (newStage === 'VIEWING_SCHEDULED' || newStage === 'VIEWING_CONFIRMED') status = 'ЗАПИСАН';
else if (action === 'transfer_to_manager') status = 'МЕНЕДЖЕР';
else if (action === 'mark_lost') status = 'ОТКАЗ';
else if (action === 'mark_won') status = 'КЛИЕНТ';
else if (action === 'set_followup') status = 'ДУМАЕТ';

const events = [];
if (newStage !== lead.current_stage) {
  events.push({event_type: 'stage_exited', from_stage: lead.current_stage, to_stage: newStage, payload: {}});
  events.push({event_type: 'stage_entered', from_stage: lead.current_stage, to_stage: newStage, payload: {}});
}
if (collected.last_objection) {
  events.push({event_type: 'objection_raised', from_stage: lead.current_stage, to_stage: newStage, payload: {objection: collected.last_objection}});
}
if (action === 'transfer_to_manager') events.push({event_type: 'transferred_to_manager', from_stage: lead.current_stage, to_stage: newStage, payload: {reason: internalNote}});
if (action === 'set_followup') events.push({event_type: 'followup_sent', from_stage: lead.current_stage, to_stage: newStage, payload: {}});
if (action === 'mark_lost') events.push({event_type: 'lead_lost', from_stage: lead.current_stage, to_stage: newStage, payload: {reason: internalNote}});
if (action === 'mark_won') events.push({event_type: 'sale_won', from_stage: lead.current_stage, to_stage: newStage, payload: {}});

return [{
  json: {
    reply, new_stage: newStage, previous_stage: lead.current_stage, action, status,
    collected_data: collected, lead_data: collectedLeadData, confidence,
    internal_note: internalNote, events, response_time_ms: responseTimeMs
  }
}];
""".strip()


def _normalize_js() -> str:
    return """
const msg = $json.message ?? $json;
const chat = msg.chat ?? {};
const from = msg.from ?? {};
const text = typeof msg.text === 'string' ? msg.text : '';
const name = [from.first_name, from.last_name].filter(Boolean).join(' ') ||
  (chat.username ? '@' + chat.username : null);
return [{
  json: {
    whatsapp_id: 'tg:' + chat.id,
    chat_id: String(chat.id),
    name,
    text,
    is_text: text.length > 0,
  }
}];
""".strip()


def build_bot() -> dict:
    known = _knewit_nodes()
    prompt = BOT_PROMPT.read_text(encoding="utf-8").rstrip()
    state_block = """

Current lead state (use it, do not ask again):
current_stage: {{ $('Upsert & Load Lead State').item.json.current_stage }}
direction: {{ $('Upsert & Load Lead State').item.json.direction }}
goal: {{ $('Upsert & Load Lead State').item.json.goal }}
preferred_format: {{ $('Upsert & Load Lead State').item.json.preferred_format }}
preferred_time: {{ $('Upsert & Load Lead State').item.json.preferred_time }}
last_objection: {{ $('Upsert & Load Lead State').item.json.last_objection }}
trial_datetime: {{ $('Upsert & Load Lead State').item.json.trial_datetime }}
name: {{ $('Upsert & Load Lead State').item.json.name }}
whatsapp_id: {{ $('Upsert & Load Lead State').item.json.whatsapp_id }}
"""
    nodes: list[dict] = []

    nodes.append(
        node(
            "Telegram Trigger",
            "n8n-nodes-base.telegramTrigger",
            1.2,
            [0, 300],
            {"updates": ["message"], "additionalFields": {}},
            credentials=TELEGRAM_CREDS,
            webhookId=nid("tcs-bot-telegram"),
        )
    )
    nodes.append(
        node(
            "Normalize Message",
            "n8n-nodes-base.code",
            2,
            [220, 300],
            {"jsCode": _normalize_js()},
        )
    )
    nodes.append(
        node(
            "Text Message?",
            "n8n-nodes-base.if",
            2.3,
            [440, 300],
            {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "strict",
                        "version": 3,
                    },
                    "conditions": [
                        {
                            "id": nid("cond-is-text"),
                            "leftValue": "={{ $json.is_text }}",
                            "rightValue": "",
                            "operator": {
                                "type": "boolean",
                                "operation": "true",
                                "singleValue": True,
                            },
                        }
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
        )
    )
    nodes.append(
        node(
            "Send Non-Text Reply",
            "n8n-nodes-base.telegram",
            1.2,
            [660, 460],
            {
                "chatId": "={{ $('Normalize Message').item.json.chat_id }}",
                "text": "Please send a text message.",
                "additionalFields": {"appendAttribution": False},
            },
            credentials=TELEGRAM_CREDS,
        )
    )
    nodes.append(
        node(
            "is bot paused?",
            "n8n-nodes-base.postgres",
            2.6,
            [660, 300],
            {
                "operation": "executeQuery",
                "query": "SELECT COALESCE((SELECT bot_paused FROM crm_conversation_state"
                " WHERE whatsapp_id = $1), false) AS bot_paused;",
                "options": {
                    "queryReplacement": "={{ [ $('Normalize Message').item.json.whatsapp_id ] }}"
                },
            },
            credentials=POSTGRES_CREDS,
        )
    )
    nodes.append(
        node(
            "Bot Paused?",
            "n8n-nodes-base.if",
            2.3,
            [880, 300],
            {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "strict",
                        "version": 3,
                    },
                    "conditions": [
                        {
                            "id": nid("cond-bot-paused"),
                            "leftValue": "={{ $json.bot_paused === true }}",
                            "rightValue": "",
                            "operator": {
                                "type": "boolean",
                                "operation": "true",
                                "singleValue": True,
                            },
                        }
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
        )
    )
    nodes.append(
        node(
            "Paused - stop",
            "n8n-nodes-base.noOp",
            1,
            [1100, 460],
            {},
        )
    )
    nodes.append(
        node(
            "Load Booked Slots",
            "n8n-nodes-base.postgres",
            2.6,
            [1100, 300],
            {
                "operation": "executeQuery",
                "query": "SELECT trial_datetime, COUNT(*) AS n FROM tcs_leads"
                " WHERE trial_datetime BETWEEN now() AND now() + interval '7 days'"
                " GROUP BY trial_datetime;",
                "options": {},
            },
            credentials=POSTGRES_CREDS,
            alwaysOutputData=True,
        )
    )
    nodes.append(
        node(
            "Upsert & Load Lead State",
            "n8n-nodes-base.postgres",
            2.6,
            [1320, 300],
            {
                "operation": "executeQuery",
                "query": "INSERT INTO tcs_leads (whatsapp_id, name, source, current_stage, status)"
                " VALUES ($1, $2, 'telegram', 'NEW_INQUIRY', 'ACTIVE')"
                " ON CONFLICT (whatsapp_id) DO UPDATE"
                " SET last_message_at = CURRENT_TIMESTAMP RETURNING *;",
                "options": {
                    "queryReplacement": "={{ [ $('Normalize Message').item.json.whatsapp_id,"
                    " $('Normalize Message').item.json.name ] }}"
                },
            },
            credentials=POSTGRES_CREDS,
            onError="continueRegularOutput",
        )
    )
    nodes.append(
        node(
            "Log Incoming Message",
            "n8n-nodes-base.postgres",
            2.6,
            [1540, 300],
            {
                "operation": "executeQuery",
                "query": "INSERT INTO tcs_messages"
                " (whatsapp_id, direction, message_type, content, stage_at_moment)"
                " VALUES ($1, 'in', 'chat', $2, $3);",
                "options": {
                    "queryReplacement": "={{ [ $('Normalize Message').item.json.whatsapp_id,"
                    " $('Normalize Message').item.json.text,"
                    " $('Upsert & Load Lead State').item.json.current_stage ] }}"
                },
            },
            credentials=POSTGRES_CREDS,
            onError="continueRegularOutput",
        )
    )
    nodes.append(
        node(
            "Build Agent Context",
            "n8n-nodes-base.code",
            2,
            [1760, 300],
            {
                "jsCode": "const booked = [];\n"
                "for (const item of $('Load Booked Slots').all()) {\n"
                "  if (item.json && item.json.trial_datetime) booked.push(item.json);\n"
                "}\n"
                "return [{ json: { booked_slots: booked, started_at: new Date().toISOString() } }];"
            },
        )
    )
    agent_params = {
        "promptType": "define",
        "text": "=" + prompt + state_block,
        "hasOutputParser": True,
        "options": {},
    }
    nodes.append(
        node(
            "AI Agent",
            "@n8n/n8n-nodes-langchain.agent",
            3.1,
            [2000, 260],
            agent_params,
            onError="continueErrorOutput",
        )
    )
    nodes.append(
        node(
            "Validate & Normalize Agent Output",
            "n8n-nodes-base.code",
            2,
            [2240, 260],
            {"jsCode": _validate_js()},
        )
    )
    nodes.append(
        node(
            "Send Reply",
            "n8n-nodes-base.telegram",
            1.2,
            [2480, 160],
            {
                "chatId": "={{ $('Normalize Message').item.json.chat_id }}",
                "text": "={{ $('Validate & Normalize Agent Output').item.json.reply }}",
                "additionalFields": {"appendAttribution": False},
            },
            credentials=TELEGRAM_CREDS,
            onError="continueErrorOutput",
            retryOnFail=True,
            maxTries=3,
            waitBetweenTries=3000,
        )
    )
    nodes.append(
        node(
            "Send Failed - stop",
            "n8n-nodes-base.noOp",
            1,
            [2720, 120],
            {},
        )
    )
    nodes.append(
        node(
            "Update Lead State",
            "n8n-nodes-base.postgres",
            2.6,
            [2720, 300],
            {
                "operation": "executeQuery",
                "query": "UPDATE tcs_leads SET"
                " current_stage = $2, previous_stage = $3, status = $4,"
                " lead_data = COALESCE(lead_data, '{}'::jsonb) || $5::jsonb,"
                " last_objection = COALESCE(NULLIF($6, ''), last_objection),"
                " direction = COALESCE(NULLIF($7, ''), direction),"
                " goal = COALESCE(NULLIF($8, ''), goal),"
                " preferred_format = COALESCE(NULLIF($9, ''), preferred_format),"
                " preferred_time = COALESCE(NULLIF($10, ''), preferred_time),"
                " confidence_last = $11,"
                " reminder_sent = CASE WHEN $2 <> current_stage THEN false ELSE reminder_sent END,"
                " last_message_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP"
                " WHERE whatsapp_id = $1;",
                "options": {
                    "queryReplacement": "={{ [ $('Normalize Message').item.json.whatsapp_id,"
                    " $('Validate & Normalize Agent Output').item.json.new_stage,"
                    " $('Validate & Normalize Agent Output').item.json.previous_stage,"
                    " $('Validate & Normalize Agent Output').item.json.status,"
                    " JSON.stringify($('Validate & Normalize Agent Output').item.json.lead_data),"
                    " $('Validate & Normalize Agent Output').item.json.collected_data.last_objection || '',"
                    " $('Validate & Normalize Agent Output').item.json.collected_data.direction || '',"
                    " $('Validate & Normalize Agent Output').item.json.collected_data.goal || '',"
                    " $('Validate & Normalize Agent Output').item.json.collected_data.preferred_format || '',"
                    " $('Validate & Normalize Agent Output').item.json.collected_data.preferred_time || '',"
                    " $('Validate & Normalize Agent Output').item.json.confidence ] }}"
                },
            },
            credentials=POSTGRES_CREDS,
            onError="continueRegularOutput",
        )
    )
    nodes.append(
        node(
            "Has Events?",
            "n8n-nodes-base.if",
            2.3,
            [2960, 300],
            {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "strict",
                        "version": 3,
                    },
                    "conditions": [
                        {
                            "id": nid("cond-has-events"),
                            "leftValue": "={{ $('Validate & Normalize Agent Output').item.json.events.length }}",
                            "rightValue": 0,
                            "operator": {"type": "number", "operation": "gt"},
                        }
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
        )
    )
    nodes.append(
        node(
            "Log Stage & Business Events",
            "n8n-nodes-base.postgres",
            2.6,
            [3200, 300],
            {
                "operation": "executeQuery",
                "query": "INSERT INTO tcs_events (whatsapp_id, event_type, from_stage, to_stage, payload)"
                " SELECT $1, e->>'event_type', e->>'from_stage', e->>'to_stage',"
                " COALESCE(e->'payload', '{}'::jsonb)"
                " FROM jsonb_array_elements($2::jsonb) AS e;",
                "options": {
                    "queryReplacement": "={{ [ $('Normalize Message').item.json.whatsapp_id,"
                    " JSON.stringify($('Validate & Normalize Agent Output').item.json.events) ] }}"
                },
            },
            credentials=POSTGRES_CREDS,
            onError="continueRegularOutput",
        )
    )
    nodes.append(
        node(
            "Log Outgoing Message",
            "n8n-nodes-base.postgres",
            2.6,
            [3440, 300],
            {
                "operation": "executeQuery",
                "query": "INSERT INTO tcs_messages"
                " (whatsapp_id, direction, message_type, content, stage_at_moment,"
                " response_time_ms, tokens_used)"
                " VALUES ($1, 'out', 'chat', $2, $3, $4, NULL);",
                "options": {
                    "queryReplacement": "={{ [ $('Normalize Message').item.json.whatsapp_id,"
                    " $('Validate & Normalize Agent Output').item.json.reply,"
                    " $('Validate & Normalize Agent Output').item.json.new_stage,"
                    " $('Validate & Normalize Agent Output').item.json.response_time_ms ] }}"
                },
            },
            credentials=POSTGRES_CREDS,
            onError="continueRegularOutput",
        )
    )
    # Agent failure: apologize and hand off to a human (CRM raises the task).
    nodes.append(
        node(
            "Send Apology",
            "n8n-nodes-base.telegram",
            1.2,
            [2480, 620],
            {
                "chatId": "={{ $('Normalize Message').item.json.chat_id }}",
                "text": "Sorry, I'm having trouble right now. Our team will message you shortly.",
                "additionalFields": {"appendAttribution": False},
            },
            credentials=TELEGRAM_CREDS,
            onError="continueRegularOutput",
        )
    )
    nodes.append(
        node(
            "Handoff to Human",
            "n8n-nodes-base.postgres",
            2.6,
            [2720, 620],
            {
                "operation": "executeQuery",
                "query": "WITH upd AS ("
                " UPDATE tcs_leads SET status = 'МЕНЕДЖЕР', updated_at = now()"
                " WHERE whatsapp_id = $1 RETURNING whatsapp_id"
                "), ev AS ("
                " INSERT INTO tcs_events (whatsapp_id, event_type, payload)"
                " SELECT $1, 'transferred_to_manager',"
                " jsonb_build_object('reason', 'agent_error')"
                " WHERE EXISTS (SELECT 1 FROM upd)"
                ") SELECT 'handed_off' AS result;",
                "options": {
                    "queryReplacement": "={{ [ $('Normalize Message').item.json.whatsapp_id ] }}"
                },
            },
            credentials=POSTGRES_CREDS,
            onError="continueRegularOutput",
        )
    )
    nodes.append(
        node(
            "Log Apology Message",
            "n8n-nodes-base.postgres",
            2.6,
            [2960, 620],
            {
                "operation": "executeQuery",
                "query": "INSERT INTO tcs_messages"
                " (whatsapp_id, direction, message_type, content, stage_at_moment)"
                " VALUES ($1, 'out', 'chat', $2,"
                " (SELECT current_stage FROM tcs_leads WHERE whatsapp_id = $1));",
                "options": {
                    "queryReplacement": "={{ [ $('Normalize Message').item.json.whatsapp_id,"
                    " $('Send Apology').item.json.text ] }}"
                },
            },
            credentials=POSTGRES_CREDS,
            onError="continueRegularOutput",
        )
    )
    # Model, memory, parser, tools (cloned params from the original workflow).
    memory_params = json.loads(
        json.dumps(known["Postgres Chat Memory"]["parameters"], ensure_ascii=False)
    )
    memory_params["sessionKey"] = "={{ $('Normalize Message').item.json.whatsapp_id }}"
    nodes.append(
        node(
            "Postgres Chat Memory",
            "@n8n/n8n-nodes-langchain.memoryPostgresChat",
            1.4,
            [2000, 1180],
            memory_params,
            credentials=POSTGRES_CREDS,
        )
    )
    nodes.append(
        node(
            "OpenRouter Chat Model",
            "@n8n/n8n-nodes-langchain.lmChatOpenRouter",
            1,
            [2240, 1180],
            known["OpenRouter Chat Model"]["parameters"],
            credentials={"openRouterApi": {"name": "OpenRouter account"}},
        )
    )
    nodes.append(
        node(
            "Structured Output Parser",
            "@n8n/n8n-nodes-langchain.outputParserStructured",
            1.2,
            [2480, 1180],
            {"schemaType": "manual", "inputSchema": _parser_schema()},
        )
    )
    nodes.append(
        node(
            "search_units",
            "n8n-nodes-base.postgresTool",
            1,
            [2000, 700],
            {
                "operation": "executeQuery",
                "query": read_spec_block("## 1. search_units", "sql"),
                "options": {
                    "queryReplacement": "={{ [ $fromAI('beds', 'Bedrooms wanted (number)',"
                    " 'number'), $fromAI('max_rent', 'Maximum monthly rent in USD', 'number'),"
                    " $fromAI('pets', 'true when the person has a pet', 'boolean') ] }}"
                },
                "toolDescription": "Search available apartments. Use for any question"
                " about availability, price, or building.",
            },
            credentials=POSTGRES_CREDS,
        )
    )
    nodes.append(
        node(
            "get_slots",
            "@n8n/n8n-nodes-langchain.toolCode",
            1,
            [2240, 700],
            {
                "description": "Offer up to 3 viewing slots (30 min, Mon-Fri 09:00-17:00"
                " America/New_York, at least 3 hours ahead, next 7 days).",
                "jsCode": read_spec_block("## 2. get_slots", "js"),
            },
        )
    )
    nodes.append(
        node(
            "book_viewing",
            "n8n-nodes-base.postgresTool",
            1,
            [2480, 700],
            {
                "operation": "executeQuery",
                "query": read_spec_block("## 3. book_viewing", "sql"),
                "options": {
                    "queryReplacement": "={{ [ $('Normalize Message').item.json.whatsapp_id,"
                    " $fromAI('slot', 'ISO 8601 datetime of the chosen slot', 'string'),"
                    " $fromAI('direction', 'Short unit line for the CRM,"
                    " e.g. 2BR · Demo Residences A · $2,150', 'string'),"
                    " $fromAI('goal', 'Move-in and budget,"
                    " e.g. Move in by Jan 1 · budget $2,200', 'string'),"
                    " $fromAI('building', 'Building name', 'string'),"
                    " $fromAI('unit_number', 'Unit number', 'string') ] }}"
                },
                "toolDescription": "Book a viewing for the chosen slot. Returns"
                " 'booked' or 'slot_taken'.",
            },
            credentials=POSTGRES_CREDS,
        )
    )
    nodes.append(
        node(
            "handoff_to_human",
            "n8n-nodes-base.postgresTool",
            1,
            [2720, 700],
            {
                "operation": "executeQuery",
                "query": read_spec_block("## 4. handoff_to_human", "sql"),
                "options": {
                    "queryReplacement": "={{ [ $('Normalize Message').item.json.whatsapp_id,"
                    " $fromAI('reason', 'Why a human is needed', 'string') ] }}"
                },
                "toolDescription": "Hand the conversation to the office team. Call for"
                " out-of-scope questions, accommodation requests, emergencies, or when"
                " you do not know the answer.",
            },
            credentials=POSTGRES_CREDS,
        )
    )
    # Google Sheets sync stays in the canvas but disabled, per the brief
    # ("убрать, не удалять"). It keeps the original params for reference.
    sheets = json.loads(
        json.dumps(known["Синхронизация лида с Google Sheets"], ensure_ascii=False)
    )
    sheets["id"] = nid("Google Sheets sync (disabled)")
    sheets["position"] = [3440, 940]
    sheets["disabled"] = True
    sheets["credentials"] = {"googleSheetsOAuth2Api": {"name": "Google Sheets account"}}
    nodes.append(sheets)
    nodes.append(
        sticky(
            "Sticky - setup",
            "## TCS Leasing Bot (Telegram)\n"
            "1. Import: Workflows -> Import from file. Attach credentials in the UI:\n"
            "   `Postgres account` (demo DB), `Telegram account` (NEW demo bot),"
            " `OpenRouter account` (model).\n"
            "2. MANUAL after import (see HUMAN_TODO.md): verify the Telegram Trigger"
            " output shape, the Postgres Tool nodes (search_units, book_viewing,"
            " handoff_to_human) and the Code Tool get_slots. Rebuild them from"
            " docs/tcs/tools-spec.md if your n8n version differs.\n"
            "3. Schema and demo data come from scripts/seed_tcs_demo.py; do not run"
            " schema nodes here.\n"
            "4. The bot writes tcs_leads / tcs_messages / tcs_events; the CRM reads them.\n"
            "5. Bot paused = crm_conversation_state.bot_paused; a manager reply pauses"
            " the bot automatically in the CRM.",
            [-220, 80],
        )
    )

    conns: dict = {}
    link(conns, "Telegram Trigger", ["Normalize Message"])
    link(conns, "Normalize Message", ["Text Message?"])
    link(conns, "Text Message?", ["is bot paused?"], output=0)
    link(conns, "Text Message?", ["Send Non-Text Reply"], output=1)
    link(conns, "Bot Paused?", [], output=0)  # connected below
    link(conns, "Bot Paused?", [], output=1)
    link(conns, "is bot paused?", ["Bot Paused?"])
    # true (paused) -> stop; false -> continue
    conns["Bot Paused?"]["main"][0] = [{"node": "Paused - stop", "type": "main", "index": 0}]
    conns["Bot Paused?"]["main"][1] = [{"node": "Load Booked Slots", "type": "main", "index": 0}]
    link(conns, "Load Booked Slots", ["Upsert & Load Lead State"])
    link(conns, "Upsert & Load Lead State", ["Log Incoming Message"])
    link(conns, "Log Incoming Message", ["Build Agent Context"])
    link(conns, "Build Agent Context", ["AI Agent"])
    link(conns, "AI Agent", ["Validate & Normalize Agent Output"], output=0)
    link(conns, "AI Agent", ["Send Apology"], output=1)
    link(conns, "Validate & Normalize Agent Output", ["Send Reply"])
    link(conns, "Send Reply", ["Update Lead State"], output=0)
    link(conns, "Send Reply", ["Send Failed - stop"], output=1)
    link(conns, "Update Lead State", ["Has Events?"])
    link(conns, "Has Events?", ["Log Stage & Business Events"], output=0)
    link(conns, "Has Events?", ["Log Outgoing Message"], output=1)
    link(conns, "Log Stage & Business Events", ["Log Outgoing Message"])
    link(conns, "Send Apology", ["Handoff to Human"])
    link(conns, "Handoff to Human", ["Log Apology Message"])
    # Tool/model/memory/parser wiring.
    for tool in TOOLS_MIN:
        link(conns, "AI Agent", [tool], kind="ai_tool", target_type="ai_tool")
    link(
        conns,
        "AI Agent",
        ["OpenRouter Chat Model"],
        kind="ai_languageModel",
        target_type="ai_languageModel",
    )
    link(
        conns,
        "AI Agent",
        ["Postgres Chat Memory"],
        kind="ai_memory",
        target_type="ai_memory",
    )
    link(
        conns,
        "AI Agent",
        ["Structured Output Parser"],
        kind="ai_outputParser",
        target_type="ai_outputParser",
    )
    # link() created four empty ai_tool branches; collapse to one branch.
    tool_refs = conns["AI Agent"]["ai_tool"][0]
    conns["AI Agent"]["ai_tool"] = [tool_refs]
    return workflow("TCS Leasing Bot (Telegram)", nodes, conns)


# ---------------------------------------------------------------------- W-C


def build_reminders() -> dict:
    reminder_sql = """
SELECT l.whatsapp_id,
       l.trial_datetime,
       to_char(l.trial_datetime AT TIME ZONE 'America/New_York',
               'Dy Mon DD, HH12:MI AM') AS local_time,
       COALESCE(u.building, 'our office') AS building,
       COALESCE(u.unit_number, 'TBD') AS unit_number,
       'Reminder: your viewing is '
         || to_char(l.trial_datetime AT TIME ZONE 'America/New_York',
                    'Dy Mon DD, HH12:MI AM')
         || ' at ' || COALESCE(u.building, 'our office')
         || ', Unit ' || COALESCE(u.unit_number, 'TBD')
         || '. Message here if you need to reschedule.' AS reminder_text
FROM tcs_leads l
LEFT JOIN tcs_units u
  ON (u.building || ' ' || u.unit_number) = (l.lead_data->>'unit')
WHERE l.trial_datetime > now()
  AND l.trial_datetime <= now() + interval '24 hours'
  AND COALESCE(l.reminder_sent, false) = false
  AND l.whatsapp_id LIKE 'tg:%'
  AND NOT EXISTS (
    SELECT 1 FROM crm_conversation_state s
    WHERE s.whatsapp_id = l.whatsapp_id AND s.bot_paused = true
  )
ORDER BY l.trial_datetime;
""".strip()
    nodes = [
        node(
            "Every 15 Minutes",
            "n8n-nodes-base.scheduleTrigger",
            1.2,
            [0, 300],
            {"rule": {"interval": [{"field": "minutes", "minutesInterval": 15}]}},
        ),
        node(
            "Find Upcoming Viewings",
            "n8n-nodes-base.postgres",
            2.6,
            [240, 300],
            {
                "operation": "executeQuery",
                "query": reminder_sql,
                "options": {},
            },
            credentials=POSTGRES_CREDS,
            alwaysOutputData=True,
        ),
        node(
            "Send Reminder",
            "n8n-nodes-base.telegram",
            1.2,
            [480, 300],
            {
                "chatId": "={{ String($json.whatsapp_id).replace(/^tg:/, '') }}",
                "text": "={{ $json.reminder_text }}",
                "additionalFields": {"appendAttribution": False},
            },
            credentials=TELEGRAM_CREDS,
            onError="continueErrorOutput",
            retryOnFail=True,
            maxTries=3,
            waitBetweenTries=3000,
        ),
        node(
            "Mark Reminder Sent & Log",
            "n8n-nodes-base.postgres",
            2.6,
            [720, 300],
            {
                "operation": "executeQuery",
                "query": "WITH upd AS ("
                " UPDATE tcs_leads SET reminder_sent = true, updated_at = now()"
                " WHERE whatsapp_id = $1"
                " AND COALESCE(reminder_sent, false) = false"
                " RETURNING whatsapp_id, current_stage"
                ") INSERT INTO tcs_messages"
                " (whatsapp_id, direction, message_type, content, stage_at_moment)"
                " SELECT whatsapp_id, 'out', 'chat', $2, current_stage FROM upd;",
                "options": {
                    "queryReplacement": "={{ [ $('Find Upcoming Viewings').item.json.whatsapp_id,"
                    " $('Find Upcoming Viewings').item.json.reminder_text ] }}"
                },
            },
            credentials=POSTGRES_CREDS,
            onError="continueRegularOutput",
        ),
        node(
            "Reminder Failed - skip",
            "n8n-nodes-base.noOp",
            1,
            [720, 480],
            {},
        ),
        sticky(
            "Sticky - reminders",
            "## TCS Viewing Reminders\n"
            "Every 15 minutes: leads with a viewing in the next 24 hours,"
            " `reminder_sent = false`, bot not paused.\n"
            "Sends the Telegram reminder, then marks `reminder_sent = true` and logs"
            " the outgoing message in tcs_messages (one transaction).\n"
            "Attach `Postgres account` and `Telegram account` after import.",
            [-220, 60],
        ),
    ]
    conns: dict = {}
    link(conns, "Every 15 Minutes", ["Find Upcoming Viewings"])
    link(conns, "Find Upcoming Viewings", ["Send Reminder"])
    link(conns, "Send Reminder", ["Mark Reminder Sent & Log"], output=0)
    link(conns, "Send Reminder", ["Reminder Failed - skip"], output=1)
    return workflow("TCS Viewing Reminders", nodes, conns)


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")


def main() -> int:
    write(OUT_SEND, build_send_message())
    write(OUT_BOT, build_bot())
    write(OUT_REMINDERS, build_reminders())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
