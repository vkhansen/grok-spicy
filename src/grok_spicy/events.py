"""Thread-safe event bus bridging the sync pipeline thread to async SSE."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """A pipeline event to be pushed to SSE subscribers."""

    type: str  # "plan", "character", "keyframe", "script", "video", "complete", "error"
    run_id: int
    data: dict[str, Any] = field(default_factory=dict)


class EventBus:
    """Thread-safe pub/sub for sync pipeline -> async SSE."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[Event]] = []
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue[Event]:
        """Create a new subscriber queue (called from async SSE endpoint)."""
        q: asyncio.Queue[Event] = asyncio.Queue()
        with self._lock:
            self._subscribers.append(q)
        logger.debug("EventBus: new subscriber (total=%d)", len(self._subscribers))
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        """Remove a subscriber queue."""
        with self._lock, contextlib.suppress(ValueError):
            self._subscribers.remove(q)
        logger.debug("EventBus: unsubscribed (total=%d)", len(self._subscribers))

    def publish(self, event: Event) -> None:
        """Push event to all subscribers (called from sync pipeline thread)."""
        with self._lock:
            count = len(self._subscribers)
            for q in self._subscribers:
                q.put_nowait(event)
        logger.debug(
            "EventBus: published type=%s, run_id=%d to %d subscriber(s)",
            event.type,
            event.run_id,
            count,
        )
