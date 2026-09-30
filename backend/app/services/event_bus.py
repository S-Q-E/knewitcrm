from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Per-subscriber queue depth. Publishers never block: when a slow consumer
# falls behind, the oldest buffered event is dropped in favor of the newest.
MAX_QUEUE_SIZE = 100


class EventBus:
    """Process-local fan-out hub for realtime UI updates (D4).

    Workers and routers publish domain events; SSE connections subscribe.
    Single-container deployment, so an in-process hub is sufficient —
    every publisher and subscriber shares the event loop.
    """

    def __init__(self, maxsize: int = MAX_QUEUE_SIZE) -> None:
        self._maxsize = maxsize
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, type: str, data: dict[str, Any] | None = None) -> int:
        """Fan out one event. Returns the number of subscribers reached."""
        event = {"type": type, "data": data or {}, "at": datetime.now(UTC).isoformat()}
        reached = 0
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    continue
            reached += 1
        return reached

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def reset(self) -> None:
        """Drop all subscribers. Tests only."""
        self._subscribers.clear()


bus = EventBus()
