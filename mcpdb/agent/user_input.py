"""Mid-execution user input queue for the agent."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class UserContext:
    """A piece of context added by the user during execution."""
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class UserInputQueue:
    """Thread-safe queue for mid-execution user input.

    Users can add context while the agent is executing via the
    `add_context` MCP tool. The agent checks the queue before
    each step and injects any new context.
    """

    def __init__(self) -> None:
        self._queue: deque[UserContext] = deque()
        self._lock = threading.Lock()

    def add(self, text: str, **metadata: Any) -> None:
        """Add user context to the queue."""
        with self._lock:
            self._queue.append(UserContext(text=text, metadata=metadata))

    def drain(self) -> list[UserContext]:
        """Get and remove all queued context items."""
        with self._lock:
            items = list(self._queue)
            self._queue.clear()
            return items

    def peek(self) -> list[UserContext]:
        """View queued items without removing them."""
        with self._lock:
            return list(self._queue)

    @property
    def has_items(self) -> bool:
        """Check if there are queued items."""
        with self._lock:
            return len(self._queue) > 0

    def clear(self) -> None:
        """Clear the queue."""
        with self._lock:
            self._queue.clear()
