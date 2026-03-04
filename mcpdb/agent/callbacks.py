"""Streaming event infrastructure — CallbackManager and StreamingEvent."""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("mcpdb.agent.callbacks")


@dataclass
class StreamingEvent:
    """An event emitted during agent execution."""

    type: str           # e.g., "classify/start", "plan/ready", "step/start"
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


# Listener type: receives a StreamingEvent
EventListener = Callable[[StreamingEvent], None]


class CallbackManager:
    """Manages event listeners and emits streaming events.

    Thread-safe for listener registration. Event emission is synchronous
    (will be connected to async MCP notifications in v0.6.x).
    """

    def __init__(self) -> None:
        self._listeners: list[EventListener] = []
        self._events: list[StreamingEvent] = []

    def add_listener(self, listener: EventListener) -> None:
        """Register an event listener."""
        self._listeners.append(listener)

    def remove_listener(self, listener: EventListener) -> None:
        """Remove an event listener."""
        self._listeners.remove(listener)

    def emit(self, event_type: str, **data: Any) -> StreamingEvent:
        """Emit an event to all listeners."""
        event = StreamingEvent(type=event_type, data=data)
        self._events.append(event)
        for listener in self._listeners:
            try:
                listener(event)
            except Exception as e:
                logger.warning("Event listener error: %s", e)
        return event

    def get_events(self) -> list[StreamingEvent]:
        """Return all emitted events (for testing/debugging)."""
        return list(self._events)

    def clear(self) -> None:
        """Clear event history."""
        self._events.clear()
