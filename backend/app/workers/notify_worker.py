from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..models import CrmTask
from ..services.automations import evaluate_automations
from ..services.notifications import notify, publish_pending
from ..services.paused import notify_long_paused
from ..services.unanswered import notify_unanswered

logger = logging.getLogger(__name__)

NOTIFY_LOCK_KEY = 91030002
NOTIFY_INTERVAL_SECONDS = 60


async def run_notify_cycle(session_factory: async_sessionmaker[AsyncSession]) -> dict:
    """Reminders for overdue/due-soon tasks plus automation evaluation."""
    async with session_factory() as session:
        async with session.begin():
            got_lock = (
                await session.execute(
                    text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": NOTIFY_LOCK_KEY}
                )
            ).scalar()
            if not got_lock:
                return {"skipped": True}
            stats: dict[str, int] = {"overdue": 0, "due_soon": 0}
            overdue, overdue_events = await _remind_overdue(session)
            due_soon, due_soon_events = await _remind_due_soon(session)
            stats["overdue"] = overdue
            stats["due_soon"] = due_soon
            unanswered_events = await notify_unanswered(session, datetime.now(UTC))
            stats["unanswered"] = len(unanswered_events)
            paused_events = await notify_long_paused(session, datetime.now(UTC))
            stats["paused_long"] = len(paused_events)
            auto = await evaluate_automations(session)
            stats["automations_evaluated"] = auto.evaluated
            stats["automations_fired"] = auto.fired
            pending = (
                overdue_events + due_soon_events + unanswered_events + paused_events + auto.events
            )
        publish_pending(pending)
    logger.info("notify cycle done %s", stats)
    return stats


async def _remind_overdue(session: AsyncSession) -> tuple[int, list[dict]]:
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(CrmTask.id, CrmTask.assignee_id, CrmTask.title).where(
                CrmTask.done_at.is_(None),
                CrmTask.due_at.is_not(None),
                CrmTask.due_at < now,
                CrmTask.assignee_id.is_not(None),
            )
        )
    ).all()
    pending: list[dict] = []
    for task_id, assignee_id, title in rows:
        pending.extend(
            await notify(
                session,
                [assignee_id],
                "task_overdue",
                {
                    "task_id": str(task_id),
                    "title": title,
                    "dedupe_key": f"task-overdue:{task_id}:{now.date().isoformat()}",
                },
            )
        )
    return len(pending), pending


async def _remind_due_soon(session: AsyncSession) -> tuple[int, list[dict]]:
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(CrmTask.id, CrmTask.assignee_id, CrmTask.title).where(
                CrmTask.done_at.is_(None),
                CrmTask.due_at.is_not(None),
                CrmTask.due_at >= now,
                CrmTask.due_at < now + timedelta(hours=24),
                CrmTask.assignee_id.is_not(None),
            )
        )
    ).all()
    pending: list[dict] = []
    for task_id, assignee_id, title in rows:
        pending.extend(
            await notify(
                session,
                [assignee_id],
                "task_due_soon",
                {
                    "task_id": str(task_id),
                    "title": title,
                    "dedupe_key": f"task-due-soon:{task_id}:{now.date().isoformat()}",
                },
            )
        )
    return len(pending), pending


async def notify_loop(
    session_factory: async_sessionmaker[AsyncSession], interval_seconds: int = 60
) -> None:
    """Background loop for lifespan. Never raises; failures are logged."""
    while True:
        try:
            await run_notify_cycle(session_factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("notify cycle failed")
        await asyncio.sleep(interval_seconds)
