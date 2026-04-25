"""In-process pub/sub for live aircraft updates.

The ingestor publishes events here. The WebSocket route subscribes and
forwards events to connected clients. Each subscriber gets its own queue
so a slow client can't slow down the publisher.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Drop messages if a client falls more than this far behind
_QUEUE_MAX = 200


class Broadcaster:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    async def publish(self, event: dict[str, Any]) -> None:
        """Send event to every subscriber. Drops events for slow clients."""
        if not self._subscribers:
            return
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("WebSocket subscriber slow, dropping event")

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)


broadcaster = Broadcaster()
