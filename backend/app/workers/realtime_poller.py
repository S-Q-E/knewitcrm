from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..services import metrics
from ..services.event_bus import EventBus, bus

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 2
# n8n inserts can commit out of id order: a later id may be visible before an
# earlier one. Each poll therefore re-reads this many ids below the cursor and
# skips ids already published (P2-2). A row that commits later than this many
# new rows is not published in realtime (it is still in the database).
OVERLAP_ROWS = 200
# On restart the stored cursor is used only when the gap is at most this many ids;
# a larger gap starts from the table maximum, so downtime never floods clients.
REPLAY_ROWS = 500
SAVE_INTERVAL_SECONDS = 10.0
CURSOR_SETTING = "realtime_poller.cursors"


class RealtimePoller:
    """Polls bot tables for new rows and fans them out on the event bus (D4).

    On start the cursors are set to the table maxima, so history is not
    replayed, unless a stored cursor (persist_cursor=True) is close enough to
    replay the gap. CRM-side changes (sync moves, outbox, pauses, tasks, deals)
    publish directly at their call sites; the poller only watches n8n-owned
    tables and never writes to them.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bus: EventBus = bus,
        *,
        persist_cursor: bool = False,
    ):
        self._factory = session_factory
        self._bus = bus
        self._persist = persist_cursor
        self._last_message_id = 0
        self._last_event_id = 0
        self._seen_messages: set[int] = set()
        self._seen_events: set[int] = set()
        self._saved: dict[str, int] | None = None
        self._saved_at = 0.0
        self._started = False

    async def start(self) -> None:
        async with self._factory() as session:
            stored = await _load_cursors(session) if self._persist else None
            msg_max = await _max_id(session, "knewit_messages")
            evt_max = await _max_id(session, "knewit_events")
            start_msg = _replay_start(stored, "message_id", msg_max)
            start_evt = _replay_start(stored, "event_id", evt_max)
            self._seen_messages = await _ids_in_window(session, "knewit_messages", start_msg)
            self._seen_events = await _ids_in_window(session, "knewit_events", start_evt)
        self._last_message_id = start_msg
        self._last_event_id = start_evt
        self._started = True
        logger.info(
            "realtime poller started from message_id=%d event_id=%d (replay=%s)",
            self._last_message_id,
            self._last_event_id,
            stored is not None and (start_msg < msg_max or start_evt < evt_max),
        )

    async def poll_once(self) -> dict[str, int]:
        """Fetch rows around the cursors and publish unseen ones. Advances cursors."""
        if not self._started:
            await self.start()
        stats = {"messages": 0, "events": 0}
        async with self._factory() as session:
            messages = (
                (
                    await session.execute(
                        text(
                            "SELECT id, whatsapp_id, direction, message_type"
                            " FROM knewit_messages WHERE id > :floor"
                            " ORDER BY id LIMIT 500"
                        ),
                        {"floor": _floor(self._last_message_id)},
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
                            " FROM knewit_events WHERE id > :floor"
                            " ORDER BY id LIMIT 500"
                        ),
                        {"floor": _floor(self._last_event_id)},
                    )
                )
                .mappings()
                .all()
            )
        for row in messages:
            if row["id"] in self._seen_messages:
                continue
            self._seen_messages.add(row["id"])
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
            if row["id"] in self._seen_events:
                continue
            self._seen_events.add(row["id"])
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
        self._seen_messages = {i for i in self._seen_messages if i > _floor(self._last_message_id)}
        self._seen_events = {i for i in self._seen_events if i > _floor(self._last_event_id)}
        await self._maybe_save()
        return stats

    async def _maybe_save(self) -> None:
        if not self._persist:
            return
        current = {"message_id": self._last_message_id, "event_id": self._last_event_id}
        if current == self._saved or time.monotonic() - self._saved_at < SAVE_INTERVAL_SECONDS:
            return
        try:
            async with self._factory() as session:
                await _store_cursors(session, current)
                await session.commit()
        except Exception as exc:
            logger.warning("realtime cursor save failed: %s", type(exc).__name__)
            return
        self._saved = current
        self._saved_at = time.monotonic()

    @property
    def cursors(self) -> dict[str, int]:
        return {"last_message_id": self._last_message_id, "last_event_id": self._last_event_id}


def _floor(cursor: int) -> int:
    return max(0, cursor - OVERLAP_ROWS)


def _replay_start(stored: dict[str, Any] | None, key: str, table_max: int) -> int:
    if not stored or not isinstance(stored.get(key), int):
        return table_max
    saved = stored[key]
    if saved > table_max or table_max - saved > REPLAY_ROWS:
        return table_max
    return saved


async def _load_cursors(session: AsyncSession) -> dict[str, Any] | None:
    value = (
        await session.execute(
            text("SELECT value FROM crm_settings WHERE key = :key"), {"key": CURSOR_SETTING}
        )
    ).scalar_one_or_none()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


async def _store_cursors(session: AsyncSession, cursors: dict[str, int]) -> None:
    await session.execute(
        text(
            "INSERT INTO crm_settings (key, value) VALUES (:key, CAST(:value AS jsonb))"
            " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {"key": CURSOR_SETTING, "value": json.dumps(cursors)},
    )


# Table names cannot be bound parameters; restrict to the two bot tables
# this poller is allowed to read (callers pass literals, never user input).
_READABLE_TABLES = frozenset({"knewit_messages", "knewit_events"})


def _checked_table(table: str) -> str:
    if table not in _READABLE_TABLES:
        raise ValueError(f"unexpected table: {table}")
    return table


async def _max_id(session: AsyncSession, table: str) -> int:
    table = _checked_table(table)
    return (await session.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table}"))).scalar() or 0


async def _ids_in_window(session: AsyncSession, table: str, cursor: int) -> set[int]:
    """Ids already at or below the cursor that the overlap re-read may see again."""
    table = _checked_table(table)
    rows = await session.execute(
        text(f"SELECT id FROM {table} WHERE id > :floor AND id <= :cursor"),
        {"floor": _floor(cursor), "cursor": cursor},
    )
    return set(rows.scalars())


async def realtime_loop(
    session_factory: async_sessionmaker[AsyncSession],
    event_bus: EventBus = bus,
    interval_seconds: int = POLL_INTERVAL_SECONDS,
) -> None:
    """Background loop for lifespan. Never raises; failures are logged."""
    poller = RealtimePoller(session_factory, event_bus, persist_cursor=True)
    await poller.start()
    while True:
        try:
            await poller.poll_once()
            metrics.mark_cycle("realtime")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("realtime poll failed")
        await asyncio.sleep(interval_seconds)
