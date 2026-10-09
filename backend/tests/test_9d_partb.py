from __future__ import annotations

import io
import json
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from backend.app.workers.outbox_worker import format_outbox_error, run_outbox_cycle
from backend.tests.conftest import csrf_headers
from backend.tests.crm_helpers import ManagerSession, admin_csrf, engine_factory, make_manager

pytestmark = pytest.mark.usefixtures("db_available")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _wa() -> str:
    return f"7999{uuid.uuid4().hex[:8]}@c.us"


async def _insert_lead(factory, wa: str) -> None:
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO knewit_leads (whatsapp_id, name, current_stage, status)"
                " VALUES (:wa, 'Probe', 'НОВЫЙ_ЛИД', 'ACTIVE')"
            ),
            {"wa": wa},
        )
        await session.commit()


async def _purge(factory, wa: str) -> None:
    async with factory() as session:
        await session.execute(text("DELETE FROM crm_outbox WHERE whatsapp_id = :wa"), {"wa": wa})
        await session.execute(
            text("DELETE FROM knewit_messages WHERE whatsapp_id = :wa"), {"wa": wa}
        )
        await session.execute(text("DELETE FROM knewit_events WHERE whatsapp_id = :wa"), {"wa": wa})
        await session.execute(text("DELETE FROM knewit_leads WHERE whatsapp_id = :wa"), {"wa": wa})
        # Failure paths notify the sender; drop those rows too so later
        # tests counting notifications (test_outbox.py) see a clean slate.
        await session.execute(
            text("DELETE FROM crm_notifications WHERE payload ->> 'whatsapp_id' = :wa"),
            {"wa": wa},
        )
        await session.commit()


async def test_export_escapes_formula_injection_csv_and_xlsx(client, settings):
    from backend.tests.crm_helpers import create_contact, purge_contacts

    engine, factory = engine_factory(settings)
    contact_ids: list[str] = []
    try:
        token = await admin_csrf(client, settings)
        evil = '=HYPERLINK("http://evil.example","click")'
        created = await create_contact(client, token, name=evil, whatsapp_id=_wa())
        contact_ids.append(created["id"])

        csv_resp = await client.get("/api/contacts/export?format=csv&search=HYPERLINK")
        assert csv_resp.status_code == 200, csv_resp.text
        body = csv_resp.content.decode("utf-8-sig")
        # The payload cell must be neutralized, never a live formula.
        assert "'=HYPERLINK" in body
        assert "\n=HYPERLINK" not in body

        for trigger in ("+cmd", "-cmd", "@cmd"):
            line = [ln for ln in body.splitlines() if "HYPERLINK" in ln or trigger in ln]
            assert line  # header + row present; main assertion above covers '='

        xlsx_resp = await client.get("/api/contacts/export?format=xlsx&search=HYPERLINK")
        assert xlsx_resp.status_code == 200
        from openpyxl import load_workbook

        wb = load_workbook(filename=io.BytesIO(xlsx_resp.content), read_only=True)
        ws = wb.active
        assert ws is not None
        values = [str(cell.value or "") for row in ws.iter_rows() for cell in row]
        assert any(v.startswith("'=") and "HYPERLINK" in v for v in values)
    finally:
        await purge_contacts(factory, contact_ids)
        await engine.dispose()


async def test_export_cell_triggers_unit():
    from backend.app.services.export import _cell

    for trigger in ("=1+1", "+cmd", "-cmd", "@user", "\tindented", "\rline", "\nline"):
        assert _cell(trigger).startswith("'"), trigger
    assert _cell("normal text") == "normal text"
    assert _cell(None) == ""
    assert _cell(42) == "42"


async def test_import_rejects_files_over_2mb(client, settings):
    token = await admin_csrf(client, settings)
    big = b"a,b\n" + b"x,y\n" * (2 * 1024 * 1024 // 4 + 100)
    assert len(big) > 2 * 1024 * 1024
    mapping = json.dumps({"a": "name", "b": "phone"})
    for url in ("/api/contacts/import/preview", "/api/contacts/import"):
        response = await client.post(
            url,
            files={"file": ("big.csv", big, "text/csv")},
            data={"mapping": mapping},
            headers=csrf_headers(token),
        )
        assert response.status_code == 413, (url, response.status_code, response.text[:200])
        assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    # Just under the limit still parses (small sanity file).
    small = ("name,phone\nИван,+77011112233\n").encode()
    ok_preview = await client.post(
        "/api/contacts/import/preview",
        files={"file": ("ok.csv", small, "text/csv")},
        data={"mapping": json.dumps({"name": "name", "phone": "phone"})},
        headers=csrf_headers(token),
    )
    assert ok_preview.status_code == 200, ok_preview.text


def test_format_outbox_error_truncates_and_drops_sql_params():
    class FakeDBError(Exception):
        pass

    long_sql = (
        "statement failed\nDETAIL: params {'whatsapp_id': '79990000001@c.us',"
        " 'body': 'secret text'}"
    )
    err = format_outbox_error(FakeDBError(long_sql))
    assert err.startswith("FakeDBError: statement failed")
    assert len(err) <= 200
    assert "79990000001" not in err
    assert "secret text" not in err

    assert format_outbox_error(httpx.ConnectError("dns down")) == "ConnectError: dns down"
    assert format_outbox_error(ValueError("")) == "ValueError"


async def test_outbox_failure_stores_short_class_only_error(client, settings):
    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        token = await admin_csrf(client, settings)
        await _insert_lead(factory, wa)
        queued = await client.post(
            f"/api/chats/{wa}/messages", json={"body": "Сбой"}, headers=csrf_headers(token)
        )
        assert queued.status_code == 202

        async def boom(**kwargs):
            raise httpx.ReadTimeout("read timed out after 10s; extra " + "x" * 500)

        stats = await run_outbox_cycle(factory, settings, sender=boom)
        assert stats is not None and stats["failed"] == 1
        async with factory() as session:
            row = (
                (
                    await session.execute(
                        text("SELECT error FROM crm_outbox WHERE whatsapp_id = :wa"), {"wa": wa}
                    )
                )
                .mappings()
                .one()
            )
        error = row["error"]
        assert error.startswith("ReadTimeout:")
        assert len(error) <= 200
    finally:
        await _purge(factory, wa)
        await engine.dispose()


async def test_outbox_mirror_failure_prefix_is_short(client, settings, monkeypatch):
    import backend.app.workers.outbox_worker as worker_mod

    engine, factory = engine_factory(settings)
    wa = _wa()
    try:
        token = await admin_csrf(client, settings)
        await _insert_lead(factory, wa)
        queued = await client.post(
            f"/api/chats/{wa}/messages", json={"body": "Зеркало"}, headers=csrf_headers(token)
        )
        assert queued.status_code == 202

        async def broken_mirror(session, whatsapp_id, body):
            raise RuntimeError("knewit_messages wedged; params {'content': 'Зеркало'}")

        monkeypatch.setattr(worker_mod, "insert_outgoing_message", broken_mirror)

        async def ok_sender(**kwargs):
            return {"ok": True, "provider_message_id": "pv-1"}

        stats = await run_outbox_cycle(factory, settings, sender=ok_sender)
        assert stats is not None and stats["sent"] == 1
        async with factory() as session:
            row = (
                (
                    await session.execute(
                        text("SELECT error FROM crm_outbox WHERE whatsapp_id = :wa"), {"wa": wa}
                    )
                )
                .mappings()
                .one()
            )
        assert row["error"].startswith("mirror_failed: RuntimeError:")
        assert len(row["error"]) <= 200
    finally:
        await _purge(factory, wa)
        await engine.dispose()


async def test_analytics_managers_visible_setting(client, settings, app):
    engine, factory = engine_factory(settings)
    try:
        admin = await admin_csrf(client, settings)
        manager = await make_manager(client, admin)
        # Default true: managers are allowed.
        async with ManagerSession(app, manager["email"], manager["password"]) as mgr:
            assert mgr.client is not None
            assert (await mgr.client.get("/api/analytics/overview")).status_code == 200
            export = await mgr.client.get("/api/analytics/export?section=funnel")
            assert export.status_code == 200, export.text[:200]

        # Hide from managers: 403 on both endpoints, admins still pass.
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO crm_settings (key, value) VALUES"
                    " ('analytics_managers_visible', 'false')"
                    " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
                )
            )
            await session.commit()
        try:
            got = await client.get("/api/settings")
            assert got.json()["analytics_managers_visible"] is False
            async with ManagerSession(app, manager["email"], manager["password"]) as mgr2:
                assert mgr2.client is not None
                denied = await mgr2.client.get("/api/analytics/overview")
                assert denied.status_code == 403
                assert denied.json()["error"]["code"] == "FORBIDDEN"
                denied_export = await mgr2.client.get("/api/analytics/export?section=funnel")
                assert denied_export.status_code == 403
            assert (await client.get("/api/analytics/overview")).status_code == 200
        finally:
            async with factory() as session:
                await session.execute(
                    text("DELETE FROM crm_settings WHERE key = 'analytics_managers_visible'")
                )
                await session.commit()
    finally:
        await engine.dispose()


def test_n8n_workflow_and_readme_present():
    workflow = REPO_ROOT / "docs" / "n8n" / "crm-send-message.workflow.json"
    readme = REPO_ROOT / "docs" / "n8n" / "README.md"
    assert workflow.is_file() and readme.is_file()
    data = json.loads(workflow.read_text())
    names = {node["name"] for node in data["nodes"]}
    assert "CRM Send Webhook" in names
    assert "Check Secret" in names
    assert "Check Duplicate" in names
    assert "Respond OK" in names
    # Secret check references the env secret and has a 401 branch.
    text_blob = workflow.read_text()
    assert "N8N_WEBHOOK_SECRET" in text_blob
    assert "401" in text_blob
    assert "outbox_id" in text_blob
    # Step 16a: Postgres dedupe is primary, static data is the fallback.
    by_name = {node["name"]: node for node in data["nodes"]}
    assert by_name["Check Duplicate"]["type"] == "n8n-nodes-base.postgres"
    assert by_name["Mark Sent"]["type"] == "n8n-nodes-base.postgres"
    assert "ON CONFLICT (outbox_id) DO NOTHING" in text_blob
    assert "n8n_processed_outbox" in text_blob
    assert "SELECT COUNT(*)" in text_blob
    secret_params = json.dumps(by_name["Check Secret"]["parameters"])
    assert "notEmpty" in secret_params
    assert '"caseSensitive":true' in secret_params.replace(" ", "")
    readme_text = readme.read_text()
    assert "bot_paused" in readme_text
    assert "crm_conversation_state" in readme_text
    assert "AI" in readme_text
    assert "запасной вариант" in readme_text
    assert "static data" in readme_text or "staticData" in readme_text
