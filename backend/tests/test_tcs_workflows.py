"""Static checks for the generated TCS n8n workflows (no DB needed)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEND = ROOT / "docs" / "n8n" / "tcs-send-message-telegram.workflow.json"
BOT = ROOT / "workflows" / "tcs_bot.json"
REMINDERS = ROOT / "workflows" / "tcs_reminders.json"


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_workflow", ROOT / "scripts" / "validate_workflow.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workflow(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_generated_workflows_validate():
    validator = _load_validator()
    for path in (SEND, BOT, REMINDERS):
        assert path.exists(), path
        assert validator.validate(path) == [], path


def test_send_message_uses_telegram_not_whatsapp():
    data = _workflow(SEND)
    names = {n["name"] for n in data["nodes"]}
    types = {n["type"] for n in data["nodes"]}
    assert "Send Telegram Message" in names
    assert "Send WhatsApp Message" not in names
    assert "n8n-nodes-base.telegram" in types
    node = next(n for n in data["nodes"] if n["name"] == "Send Telegram Message")
    assert node.get("onError") == "continueErrorOutput"
    # Telegram chat id = whatsapp_id without the tg: prefix.
    assert "replace(/^tg:/" in node["parameters"]["chatId"]


def test_bot_workflow_targets_tcs_tables_only():
    text = BOT.read_text(encoding="utf-8")
    assert "knewit_" not in text.lower()
    assert "tcs_leads" in text and "tcs_messages" in text and "tcs_events" in text
    data = _workflow(BOT)
    types = {n["type"] for n in data["nodes"]}
    assert "n8n-nodes-base.telegramTrigger" in types
    # No Google Sheets sync and no schema setup nodes in the demo bot.
    assert not any("googleSheets" in t for t in types)
    # Tool nodes are attached to the agent.
    connections = data["connections"]["AI Agent"]
    tools = {t["node"] for t in connections["ai_tool"][0]}
    assert tools == {"search_units", "get_slots", "book_viewing", "handoff_to_human"}


def test_bot_prompt_is_the_documented_prompt():
    prompt = (ROOT / "docs" / "tcs" / "bot-prompt.md").read_text(encoding="utf-8").rstrip()
    agent = next(n for n in _workflow(BOT)["nodes"] if n["name"] == "AI Agent")
    assert agent["parameters"]["text"].startswith("=" + prompt)


def test_reminders_every_15_minutes():
    trigger = next(
        n for n in _workflow(REMINDERS)["nodes"] if n["type"] == "n8n-nodes-base.scheduleTrigger"
    )
    interval = trigger["parameters"]["rule"]["interval"][0]
    assert interval == {"field": "minutes", "minutesInterval": 15}
    text = REMINDERS.read_text(encoding="utf-8")
    assert "reminder_sent = true" in text
    assert "interval '24 hours'" in text
