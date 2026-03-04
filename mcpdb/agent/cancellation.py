"""Thread-safe cancellation token for agent execution."""

from __future__ import annotations

import threading


class CancelledException(Exception):
    """Raised when execution is cancelled."""
    pass


class CancellationToken:
    """Thread-safe cancellation signal.

    Check `is_cancelled` at natural pause points (before each step,
    before each LLM call) and raise CancelledException if set.
    """

    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        """Signal cancellation."""
        self._cancelled.set()

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._cancelled.is_set()

    def check(self) -> None:
        """Raise CancelledException if cancelled."""
        if self._cancelled.is_set():
            raise CancelledException("Execution cancelled by user")

    def reset(self) -> None:
        """Reset the cancellation state."""
        self._cancelled.clear()
