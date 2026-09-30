from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..services.event_bus import EventBus, bus

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 2


class RealtimePoller:
    """Polls bot tables for new rows and fans them out on the event bus (D4).

    Cursors live in process memory; on start they are set to the current
    table maxima so a restart never replays history. CRM-side changes (sync
    moves, outbox, pauses, tasks, deals) publish directly at their call
    sites — the poller only watches n8n-owned tables, which it must never
    write to.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], bus: EventBus = bus):
        self._factory = session_factory
        self._bus = bus
        self._last_message_id = 0
        self._last_event_id = 0
        self._started = False

    async def start(self) -> None:
        async with self._factory() as session:
            self._last_message_id = await _max_id(session, "knewit_messages")
            self._last_event_id = await _max_id(session, "knewit_events")
        self._started = True
        logger.info(
            "realtime poller started from message_id=%d event_id=%d",
            self._last_message_id,
            self._last_event_id,
        )

    async def poll_once(self) -> dict[str, int]:
        """Fetch rows after the cursors and publish them. Advances cursors."""
        if not self._started:
            await self.start()
        stats = {"messages": 0, "events": 0}
        async with self._factory() as session:
            messages = (
                (
                    await session.execute(
                        text(
                            "SELECT id, whatsapp_id, direction, message_type"
                            " FROM knewit_messages WHERE id > :last"
                            " ORDER BY id LIMIT 500"
                        ),
                        {"last": self._last_message_id},
                    )
                )
                .mappings()
                .all()
            )
            events = (
                (
                    await session.execute(
                        text(
                            "SELECT id, whatsapp_id, event_type, from_stage, to_stage"
                            " FROM knewit_events WHERE id > :last"
                            " ORDER BY id LIMIT 500"
                        ),
                        {"last": self._last_event_id},
                    )
                )
                .mappings()
                .all()
            )
        for row in messages:
            self._last_message_id = max(self._last_message_id, row["id"])
            self._bus.publish(
                "new_message",
                {
                    "message_id": row["id"],
                    "whatsapp_id": row["whatsapp_id"],
                    "direction": row["direction"],
                    "message_type": row["message_type"],
                },
            )
            stats["messages"] += 1
        for row in events:
            self._last_event_id = max(self._last_event_id, row["id"])
            self._bus.publish(
                "bot_event",
                {
                    "event_id": row["id"],
                    "whatsapp_id": row["whatsapp_id"],
                    "event_type": row["event_type"],
                    "from_stage": row["from_stage"],
                    "to_stage": row["to_stage"],
                },
            )
            stats["events"] += 1
        return stats

    @property
    def cursors(self) -> dict[str, int]:
        return {"last_message_id": self._last_message_id, "last_event_id": self._last_event_id}


async def _max_id(session: AsyncSession, table: str) -> int:
    return (await session.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table}"))).scalar() or 0


async def realtime_loop(
    session_factory: async_sessionmaker[AsyncSession],
    event_bus: EventBus = bus,
    interval_seconds: int = POLL_INTERVAL_SECONDS,
) -> None:
    """Background loop for lifespan. Never raises; failures are logged."""
    poller = RealtimePoller(session_factory, event_bus)
    await poller.start()
    while True:
        try:
            await poller.poll_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("realtime poll failed")
        await asyncio.sleep(interval_seconds)
