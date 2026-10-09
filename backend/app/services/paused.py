"""Dialogs whose bot pause has lasted longer than the threshold (P3-2).

Only notifications for now: the list filter stays out of scope, and auto-return
is deferred until the CRM flag is connected to Chatflow (roadmap P0-1″).
Writes only crm_notifications rows, through services/notifications.notify().
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CrmConversationState, CrmNotification, CrmUser
from .notifications import notify

SETTING_KEY = "paused_alert_hours"
DEFAULT_HOURS = 6
MIN_HOURS = 1
MAX_HOURS = 50
NOTIFY_TYPE = "bot_paused_long"


async def threshold_hours(session: AsyncSession) -> int:
    value = (
        await session.execute(
            text("SELECT value FROM crm_settings WHERE key = :key"), {"key": SETTING_KEY}
        )
    ).scalar_one_or_none()
    if isinstance(value, int) and not isinstance(value, bool):
        if MIN_HOURS <= value <= MAX_HOURS:
            return value
    return DEFAULT_HOURS


async def notify_long_paused(session: AsyncSession, now: datetime) -> list[dict]:
    """Notify every active user once per pause episode that outlasted the threshold.

    An episode is one pause: its dedupe key carries ``paused_at``, so a new pause
    after a resume starts a new episode. The key is checked against all
    notifications, read or not. Runs under the notify worker's advisory lock.
    """
    cut = now - timedelta(hours=await threshold_hours(session))
    rows = (
        await session.execute(
            select(CrmConversationState.whatsapp_id, CrmConversationState.paused_at).where(
                CrmConversationState.bot_paused.is_(True),
                CrmConversationState.paused_at.is_not(None),
                CrmConversationState.paused_at < cut,
            )
        )
    ).all()
    if not rows:
        return []

    keys = {wa: f"paused:{wa}:{at.isoformat()}" for wa, at in rows}
    existing = set(
        (
            await session.execute(
                select(CrmNotification.dedupe_key).where(
                    CrmNotification.type == NOTIFY_TYPE,
                    CrmNotification.dedupe_key.in_(list(keys.values())),
                )
            )
        ).scalars()
    )
    users = list(
        (await session.execute(select(CrmUser.id).where(CrmUser.is_active.is_(True)))).scalars()
    )
    pending: list[dict] = []
    for wa, at in rows:
        key = keys[wa]
        if key in existing or not users:
            continue
        pending.extend(
            await notify(
                session,
                users,
                NOTIFY_TYPE,
                {
                    "whatsapp_id": wa,
                    "paused_at": at.isoformat(),
                    "hours": int((now - at).total_seconds() // 3600),
                    "dedupe_key": key,
                },
            )
        )
    return pending
