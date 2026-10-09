"""Operational gauges for /api/metrics: lags, backlogs, live connections.

Read on demand from the database and the in-process worker marks, so the
numbers show what the workers did last, not a sampled value. Read-only.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CrmConversationState
from ..workers.sync_worker import SETTINGS_KEY_LAST_FULL, SETTINGS_KEY_LAST_SYNCED, _load_marker
from .event_bus import EventBus
from .metrics import cycle_age_seconds
from .unanswered import cutoff as unanswered_cutoff
from .unanswered import unanswered_clause


def _age(now: datetime, moment: datetime | None) -> float | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0.0, round((now - moment).total_seconds(), 1))


async def ops_gauges(session: AsyncSession, event_bus: EventBus) -> list[str]:
    """Prometheus lines. A gauge without a known value is omitted, not zeroed."""
    now = datetime.now(UTC)
    lines: list[str] = []

    def emit(name: str, value: float | int | None, labels: str = "") -> None:
        if value is not None:
            lines.append(f"{name}{labels} {value}")

    emit(
        "crm_sync_lag_seconds",
        _age(now, await _load_marker(session, SETTINGS_KEY_LAST_SYNCED)),
    )
    emit(
        "crm_sync_full_lag_seconds",
        _age(now, await _load_marker(session, SETTINGS_KEY_LAST_FULL)),
    )
    emit("crm_realtime_poll_age_seconds", _rounded(cycle_age_seconds("realtime")))

    queued = (
        await session.execute(
            text(
                "SELECT MIN(COALESCE(next_attempt_at, created_at))"
                " FROM crm_outbox WHERE status = 'queued'"
            )
        )
    ).scalar()
    sending = (
        await session.execute(
            text("SELECT MIN(claimed_at) FROM crm_outbox WHERE status = 'sending'")
        )
    ).scalar()
    # Empty backlog reads as 0: the age of "nothing waiting" is zero.
    emit(
        "crm_outbox_oldest_due_seconds",
        _age(now, queued) or 0.0,
        '{status="queued"}',
    )
    emit(
        "crm_outbox_oldest_due_seconds",
        _age(now, sending) or 0.0,
        '{status="sending"}',
    )

    unanswered = (
        await session.execute(
            select(func.count())
            .select_from(CrmConversationState)
            .where(unanswered_clause(await unanswered_cutoff(session, now)))
        )
    ).scalar()
    emit("crm_unanswered_dialogs", int(unanswered or 0))
    emit("crm_sse_subscribers", event_bus.subscriber_count())
    return lines


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 1)
