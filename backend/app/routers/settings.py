from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_role
from ..deps import get_session, get_settings
from ..errors import ApiError
from ..schemas.settings import (
    BotStagesOut,
    FailedOutboxSummary,
    IntegrationsOut,
    SettingsOut,
    SettingsUpdate,
)
from ..services.activity import diff_payload, log_activity
from ..services.assignment import (
    MODE_ROUND_ROBIN,
    MODE_UNASSIGNED,
    SETTING_ASSIGNMENT,
    get_assignment_mode,
)
from ..services.unanswered import SETTING_KEY, threshold_minutes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

require_admin = require_role("admin")

SETTING_RESTRICT = "restrict_managers_to_own"
SETTING_AUTOPAUSE_MANAGER = "auto_pause_on_manager"
SETTING_AUTOPAUSE_REPLY = "auto_pause_on_manual_reply"
SETTING_ANALYTICS_MANAGERS = "analytics_managers_visible"


async def _read_bool(session: AsyncSession, key: str, default: bool) -> bool:
    value = (
        await session.execute(text("SELECT value FROM crm_settings WHERE key = :key"), {"key": key})
    ).scalar_one_or_none()
    if value is None:
        return default
    return value is True


async def _write_setting(session: AsyncSession, key: str, value: object) -> None:
    await session.execute(
        text(
            "INSERT INTO crm_settings (key, value) VALUES (:key, CAST(:value AS jsonb))"
            " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {"key": key, "value": json.dumps(value)},
    )


async def current_settings(session: AsyncSession) -> SettingsOut:
    return SettingsOut(
        restrict_managers_to_own=await _read_bool(session, SETTING_RESTRICT, False),
        auto_pause_on_manager=await _read_bool(session, SETTING_AUTOPAUSE_MANAGER, False),
        auto_pause_on_manual_reply=await _read_bool(session, SETTING_AUTOPAUSE_REPLY, True),
        analytics_managers_visible=await _read_bool(session, SETTING_ANALYTICS_MANAGERS, True),
        deal_assignment_mode=await get_assignment_mode(session),
        unanswered_after_minutes=await threshold_minutes(session),
    )


@router.get("", response_model=SettingsOut)
async def get_settings_view(
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    del admin
    return await current_settings(session)


@router.patch("", response_model=SettingsOut)
async def update_settings(
    payload: SettingsUpdate,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    before = (await current_settings(session)).model_dump()
    if payload.restrict_managers_to_own is not None:
        await _write_setting(session, SETTING_RESTRICT, payload.restrict_managers_to_own)
    if payload.auto_pause_on_manager is not None:
        await _write_setting(session, SETTING_AUTOPAUSE_MANAGER, payload.auto_pause_on_manager)
    if payload.auto_pause_on_manual_reply is not None:
        await _write_setting(session, SETTING_AUTOPAUSE_REPLY, payload.auto_pause_on_manual_reply)
    if payload.analytics_managers_visible is not None:
        await _write_setting(
            session, SETTING_ANALYTICS_MANAGERS, payload.analytics_managers_visible
        )
    if payload.unanswered_after_minutes is not None:
        await _write_setting(session, SETTING_KEY, payload.unanswered_after_minutes)
    if payload.deal_assignment_mode is not None:
        mode = payload.deal_assignment_mode
        if mode not in (MODE_UNASSIGNED, MODE_ROUND_ROBIN):
            raise ApiError("UNKNOWN_MODE", "Unknown assignment mode", 422)
        row = (
            await session.execute(
                text("SELECT value FROM crm_settings WHERE key = :key"),
                {"key": SETTING_ASSIGNMENT},
            )
        ).scalar_one_or_none()
        last_index = row.get("last_index", -1) if isinstance(row, dict) else -1
        if not isinstance(last_index, int):
            last_index = -1
        await _write_setting(session, SETTING_ASSIGNMENT, {"mode": mode, "last_index": last_index})
    after = await current_settings(session)
    await log_activity(
        session,
        admin.id,
        "settings",
        None,
        "settings_updated",
        diff_payload(before, after.model_dump()),
    )
    await session.commit()
    return after


@router.get("/bot-stages", response_model=BotStagesOut)
async def bot_stages(
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Real bot values for the stage editor dropdowns (read-only on knewit_*)."""
    del admin
    stages = (
        (
            await session.execute(
                text(
                    "SELECT DISTINCT current_stage FROM knewit_leads"
                    " WHERE current_stage IS NOT NULL ORDER BY 1"
                )
            )
        )
        .scalars()
        .all()
    )
    statuses = (
        (await session.execute(text("SELECT DISTINCT status FROM knewit_leads ORDER BY 1")))
        .scalars()
        .all()
    )
    return BotStagesOut(stages=[str(s) for s in stages], statuses=[str(s) for s in statuses])


@router.get("/integrations", response_model=IntegrationsOut)
async def integrations_status(
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Bot DB reachability (read-only probes) + n8n webhook config (no secret)."""
    del admin
    app_settings = get_settings()
    out = IntegrationsOut(
        bot_db_ok=False,
        n8n_configured=bool(app_settings.n8n_send_webhook_url),
        n8n_webhook_url=app_settings.n8n_send_webhook_url or None,
    )
    started = time.perf_counter()
    try:
        leads = (await session.execute(text("SELECT COUNT(*) FROM knewit_leads"))).scalar() or 0
        messages = (
            await session.execute(text("SELECT COUNT(*) FROM knewit_messages"))
        ).scalar() or 0
        events = (await session.execute(text("SELECT COUNT(*) FROM knewit_events"))).scalar() or 0
    except Exception as exc:
        logger.warning("bot db probe failed: %s", type(exc).__name__)
        out.bot_db_error = "unreachable"
    else:
        out.bot_db_ok = True
        out.bot_db_latency_ms = round((time.perf_counter() - started) * 1000, 1)
        out.leads_count = int(leads)
        out.messages_count = int(messages)
        out.events_count = int(events)

    counts = (
        (await session.execute(text("SELECT status, COUNT(*) FROM crm_outbox GROUP BY status")))
        .mappings()
        .all()
    )
    by_status = {row["status"]: int(row["count"]) for row in counts}
    out.outbox_queued = by_status.get("queued", 0)
    out.outbox_sending = by_status.get("sending", 0)
    out.outbox_sent = by_status.get("sent", 0)
    out.outbox_failed = by_status.get("failed", 0)
    last = (
        (
            await session.execute(
                text(
                    "SELECT id, whatsapp_id, error, attempts, created_at FROM crm_outbox"
                    " WHERE status = 'failed' ORDER BY created_at DESC LIMIT 1"
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if last is not None:
        out.last_failed = FailedOutboxSummary(
            id=last["id"],
            whatsapp_id=last["whatsapp_id"],
            error=last["error"],
            attempts=int(last["attempts"]),
            created_at=last["created_at"],
        )
    return out
