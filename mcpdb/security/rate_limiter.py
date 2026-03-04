"""Rate limiting and circuit breakers for queries and LLM calls."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("mcpdb.security.rate_limiter")


class RateLimitExceeded(Exception):
    """Raised when a rate limit is exceeded."""
    pass


class CircuitBreakerOpen(Exception):
    """Raised when a circuit breaker is open."""
    pass


@dataclass
class RateLimiterConfig:
    """Configuration for rate limiting."""

    max_concurrent_queries: int = 5
    max_queries_per_minute: int = 30
    max_llm_calls_per_minute: int = 20


class RateLimiter:
    """Token-bucket rate limiter with sliding window."""

    def __init__(self, max_per_minute: int = 30) -> None:
        self._max = max_per_minute
        self._timestamps: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Acquire a rate limit token. Raises RateLimitExceeded if limit reached."""
        now = time.time()
        with self._lock:
            # Remove timestamps older than 1 minute
            cutoff = now - 60.0
            self._timestamps = [t for t in self._timestamps if t > cutoff]

            if len(self._timestamps) >= self._max:
                raise RateLimitExceeded(
                    f"Rate limit exceeded: {self._max} requests per minute"
                )

            self._timestamps.append(now)

    def current_count(self) -> int:
        """Current number of requests in the sliding window."""
        now = time.time()
        cutoff = now - 60.0
        with self._lock:
            return sum(1 for t in self._timestamps if t > cutoff)

    def reset(self) -> None:
        """Reset the rate limiter."""
        with self._lock:
            self._timestamps.clear()


class ConcurrencyLimiter:
    """Limit concurrent operations using a semaphore."""

    def __init__(self, max_concurrent: int = 5) -> None:
        self._semaphore = threading.Semaphore(max_concurrent)
        self._max = max_concurrent
        self._active = 0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Acquire a concurrency slot. Raises RateLimitExceeded if all slots taken."""
        acquired = self._semaphore.acquire(blocking=False)
        if not acquired:
            raise RateLimitExceeded(
                f"Concurrency limit exceeded: {self._max} concurrent operations"
            )
        with self._lock:
            self._active += 1

    def release(self) -> None:
        """Release a concurrency slot."""
        self._semaphore.release()
        with self._lock:
            self._active = max(0, self._active - 1)

    @property
    def active_count(self) -> int:
        with self._lock:
            return self._active


class CircuitBreaker:
    """Circuit breaker pattern for external service calls.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Requests fail fast after too many consecutive failures
    - HALF_OPEN: Allow one test request to check if service recovered
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        name: str = "default",
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._name = name

        self._state = "closed"  # closed, open, half_open
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == "open":
                if time.time() - self._last_failure_time > self._recovery_timeout:
                    self._state = "half_open"
            return self._state

    def check(self) -> None:
        """Check if the circuit breaker allows the request.

        Raises CircuitBreakerOpen if in open state.
        """
        state = self.state
        if state == "open":
            raise CircuitBreakerOpen(
                f"Circuit breaker '{self._name}' is open after "
                f"{self._failure_count} consecutive failures"
            )

    def record_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            self._failure_count = 0
            self._state = "closed"

    def record_failure(self) -> None:
        """Record a failed call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self._failure_threshold:
                self._state = "open"
                logger.warning(
                    "Circuit breaker '%s' opened after %d failures",
                    self._name,
                    self._failure_count,
                )

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        with self._lock:
            self._failure_count = 0
            self._state = "closed"

    def get_stats(self) -> dict[str, Any]:
        """Get circuit breaker stats."""
        with self._lock:
            return {
                "name": self._name,
                "state": self._state,
                "failure_count": self._failure_count,
                "threshold": self._failure_threshold,
                "recovery_timeout": self._recovery_timeout,
            }
