"""Thread-safe cancellation and skip tokens for agent execution."""

from __future__ import annotations

import threading


class CancelledException(Exception):
    """Raised when execution is cancelled."""
    pass


class CancellationToken:
    """Thread-safe cancellation signal.

    Check `is_cancelled` at natural pause points (before each step,
    before each LLM call) and raise CancelledException if set.

    Also supports a "skip" signal for sequential/deep modes: skip the
    current step without aborting the entire query.
    """

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._skip = threading.Event()

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

    # ── Skip support (for sequential/deep metamodes) ──

    def request_skip(self) -> None:
        """Signal that the current step should be skipped."""
        self._skip.set()

    def consume_skip(self) -> bool:
        """Check and clear the skip flag. Returns True if skip was requested."""
        if self._skip.is_set():
            self._skip.clear()
            return True
        return False

    @property
    def is_skip_requested(self) -> bool:
        """Check if a skip has been requested (without consuming it)."""
        return self._skip.is_set()
