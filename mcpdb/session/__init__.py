"""Session lifecycle management — IDs, TTL, cleanup, limits."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("mcpdb.session")

# Default session configuration
DEFAULT_TTL = 3600  # 1 hour
DEFAULT_MAX_SESSIONS = 10


@dataclass
class Session:
    """Represents a single client session."""

    session_id: str
    created_at: float
    last_activity: float
    ttl: int = DEFAULT_TTL
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.last_activity) > self.ttl

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = time.time()

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_activity


def _generate_session_id() -> str:
    """Generate a short, unique session ID."""
    return f"s_{uuid.uuid4().hex[:8]}"


class SessionManager:
    """Thread-safe manager for client sessions.

    Handles creation, lookup, cleanup, and enforces concurrency limits.
    """

    def __init__(
        self,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        default_ttl: int = DEFAULT_TTL,
    ) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._max_sessions = max_sessions
        self._default_ttl = default_ttl

    def create_session(
        self,
        session_id: str | None = None,
        ttl: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """Create a new session.

        Raises ValueError if max sessions reached.
        """
        self._cleanup_expired()

        with self._lock:
            if len(self._sessions) >= self._max_sessions:
                raise ValueError(
                    f"Maximum sessions ({self._max_sessions}) reached. "
                    "Disconnect an existing session first."
                )

            sid = session_id or _generate_session_id()
            if sid in self._sessions:
                raise ValueError(f"Session '{sid}' already exists")

            now = time.time()
            session = Session(
                session_id=sid,
                created_at=now,
                last_activity=now,
                ttl=ttl or self._default_ttl,
                metadata=metadata or {},
            )
            self._sessions[sid] = session
            logger.info("Session created: %s (TTL=%ds)", sid, session.ttl)
            return session

    def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID, returning None if not found or expired."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if session.is_expired:
                self._sessions.pop(session_id, None)
                logger.info("Session expired and removed: %s", session_id)
                return None
            session.touch()
            return session

    def get_or_create(
        self,
        session_id: str = "default",
        ttl: int | None = None,
    ) -> Session:
        """Get existing session or create new one."""
        session = self.get_session(session_id)
        if session is not None:
            return session
        return self.create_session(session_id=session_id, ttl=ttl)

    def remove_session(self, session_id: str) -> bool:
        """Remove a session. Returns True if found and removed."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session:
            logger.info("Session removed: %s (age=%.0fs)", session_id, session.age_seconds)
            return True
        return False

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return info about all active sessions."""
        self._cleanup_expired()
        with self._lock:
            return [
                {
                    "session_id": s.session_id,
                    "created_at": s.created_at,
                    "last_activity": s.last_activity,
                    "age_seconds": s.age_seconds,
                    "idle_seconds": s.idle_seconds,
                    "ttl": s.ttl,
                    "metadata": s.metadata,
                }
                for s in self._sessions.values()
            ]

    def get_status(self, session_id: str) -> dict[str, Any] | None:
        """Get detailed status for a specific session."""
        session = self.get_session(session_id)
        if session is None:
            return None
        return {
            "session_id": session.session_id,
            "created_at": session.created_at,
            "last_activity": session.last_activity,
            "age_seconds": session.age_seconds,
            "idle_seconds": session.idle_seconds,
            "ttl": session.ttl,
            "is_expired": session.is_expired,
            "metadata": session.metadata,
        }

    def _cleanup_expired(self) -> int:
        """Remove all expired sessions. Returns count of removed sessions."""
        removed = 0
        with self._lock:
            expired = [
                sid for sid, s in self._sessions.items()
                if s.is_expired
            ]
            for sid in expired:
                self._sessions.pop(sid)
                removed += 1
        if removed:
            logger.info("Cleaned up %d expired session(s)", removed)
        return removed

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def __len__(self) -> int:
        return self.active_count

    def __contains__(self, session_id: str) -> bool:
        return self.get_session(session_id) is not None
