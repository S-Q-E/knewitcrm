from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..models import CrmTask
from ..services.automations import evaluate_automations
from ..services.notifications import already_notified, notify, publish_pending
from ..services.paused import notify_long_paused
from ..services.unanswered import notify_unanswered

logger = logging.getLogger(__name__)

NOTIFY_LOCK_KEY = 91030002
NOTIFY_INTERVAL_SECONDS = 60


async def run_notify_cycle(session_factory: async_sessionmaker[AsyncSession]) -> dict:
    """Reminders, unanswered and paused alerts, and automations, one savepoint per stage.

    A failing stage rolls back only its own writes; the other stages still commit.
    """
    async with session_factory() as session:
        async with session.begin():
            got_lock = (
                await session.execute(
                    text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": NOTIFY_LOCK_KEY}
                )
            ).scalar()
            if not got_lock:
                return {"skipped": True}
            stats: dict[str, int] = {
                "overdue": 0,
                "due_soon": 0,
                "unanswered": 0,
                "paused_long": 0,
                "automations_evaluated": 0,
                "automations_fired": 0,
            }
            pending: list[dict] = []
            for name, stage in (
                ("overdue", _remind_overdue),
                ("due_soon", _remind_due_soon),
                ("unanswered", _unanswered_stage),
                ("paused_long", _paused_stage),
                ("automations", _automation_stage),
            ):
                counts, events = await _run_stage(session, name, stage)
                stats.update(counts)
                pending.extend(events)
        publish_pending(pending)
    logger.info("notify cycle done %s", stats)
    return stats


async def _run_stage(session: AsyncSession, name: str, stage) -> tuple[dict[str, int], list[dict]]:
    try:
        async with session.begin_nested():
            return await stage(session)
    except Exception:
        logger.exception("notify stage failed stage=%s", name)
        return {}, []


async def _unanswered_stage(session: AsyncSession) -> tuple[dict[str, int], list[dict]]:
    events = await notify_unanswered(session, datetime.now(UTC))
    return {"unanswered": len(events)}, events


async def _paused_stage(session: AsyncSession) -> tuple[dict[str, int], list[dict]]:
    events = await notify_long_paused(session, datetime.now(UTC))
    return {"paused_long": len(events)}, events


async def _automation_stage(session: AsyncSession) -> tuple[dict[str, int], list[dict]]:
    auto = await evaluate_automations(session)
    return {
        "automations_evaluated": auto.evaluated,
        "automations_fired": auto.fired,
    }, auto.events


async def _remind_overdue(session: AsyncSession) -> tuple[dict[str, int], list[dict]]:
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
        key = f"task-overdue:{task_id}:{now.date().isoformat()}"
        if await already_notified(session, assignee_id, "task_overdue", key):
            continue
        pending.extend(
            await notify(
                session,
                [assignee_id],
                "task_overdue",
                {"task_id": str(task_id), "title": title, "dedupe_key": key},
            )
        )
    return {"overdue": len(pending)}, pending


async def _remind_due_soon(session: AsyncSession) -> tuple[dict[str, int], list[dict]]:
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
        key = f"task-due-soon:{task_id}:{now.date().isoformat()}"
        if await already_notified(session, assignee_id, "task_due_soon", key):
            continue
        pending.extend(
            await notify(
                session,
                [assignee_id],
                "task_due_soon",
                {"task_id": str(task_id), "title": title, "dedupe_key": key},
            )
        )
    return {"due_soon": len(pending)}, pending


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
