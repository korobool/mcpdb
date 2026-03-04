"""Session manager — persistent sessions with multi-user support."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("mcpdb.session")


@dataclass
class SessionData:
    """Serializable session state."""

    session_id: str
    created_at: float
    last_active: float
    sources: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "sources": self.sources,
            "messages": self.messages,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SessionData:
        return cls(
            session_id=d["session_id"],
            created_at=d["created_at"],
            last_active=d["last_active"],
            sources=d.get("sources", []),
            messages=d.get("messages", []),
            metadata=d.get("metadata", {}),
        )


class SessionManager:
    """Manages persistent sessions with disk storage.

    Sessions are saved as JSON files in the storage directory.
    Supports multi-session with configurable concurrency limit.
    """

    def __init__(
        self,
        storage_dir: str = "~/.mcpdb/sessions",
        max_concurrent: int = 10,
        ttl_hours: int = 24,
    ) -> None:
        self._storage_dir = Path(os.path.expanduser(storage_dir))
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._max_concurrent = max_concurrent
        self._ttl_seconds = ttl_hours * 3600
        # Active sessions in memory
        self._active: dict[str, SessionData] = {}

    def create_session(self, metadata: dict[str, Any] | None = None) -> SessionData:
        """Create a new session."""
        if len(self._active) >= self._max_concurrent:
            self._cleanup_expired()
            if len(self._active) >= self._max_concurrent:
                raise RuntimeError(
                    f"Max concurrent sessions ({self._max_concurrent}) reached"
                )

        now = time.time()
        session = SessionData(
            session_id=str(uuid.uuid4())[:8],
            created_at=now,
            last_active=now,
            metadata=metadata or {},
        )
        self._active[session.session_id] = session
        self._save(session)
        logger.info("Created session %s", session.session_id)
        return session

    def get_session(self, session_id: str) -> SessionData | None:
        """Get an active session by ID."""
        session = self._active.get(session_id)
        if session:
            session.last_active = time.time()
            return session

        # Try loading from disk
        session = self._load(session_id)
        if session and not self._is_expired(session):
            self._active[session_id] = session
            session.last_active = time.time()
            return session

        return None

    def update_session(
        self,
        session_id: str,
        sources: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update a session's state."""
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f"Session '{session_id}' not found")

        if sources is not None:
            session.sources = sources
        if messages is not None:
            session.messages = messages
        if metadata is not None:
            session.metadata.update(metadata)

        session.last_active = time.time()
        self._save(session)

    def close_session(self, session_id: str) -> None:
        """Close and remove a session."""
        self._active.pop(session_id, None)
        path = self._session_path(session_id)
        if path.exists():
            path.unlink()
        logger.info("Closed session %s", session_id)

    def list_sessions(self) -> list[SessionData]:
        """List all active sessions."""
        # Merge in-memory and disk sessions
        all_sessions = {}
        for session in self._active.values():
            all_sessions[session.session_id] = session

        for path in self._storage_dir.glob("*.json"):
            sid = path.stem
            if sid not in all_sessions:
                session = self._load(sid)
                if session and not self._is_expired(session):
                    all_sessions[sid] = session

        return sorted(all_sessions.values(), key=lambda s: s.last_active, reverse=True)

    def export_session(self, session_id: str) -> str:
        """Export a session as JSON string."""
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f"Session '{session_id}' not found")
        return json.dumps(session.to_dict(), indent=2)

    def import_session(self, json_str: str) -> SessionData:
        """Import a session from JSON string."""
        data = json.loads(json_str)
        session = SessionData.from_dict(data)
        session.last_active = time.time()
        self._active[session.session_id] = session
        self._save(session)
        logger.info("Imported session %s", session.session_id)
        return session

    def _session_path(self, session_id: str) -> Path:
        return self._storage_dir / f"{session_id}.json"

    def _save(self, session: SessionData) -> None:
        path = self._session_path(session.session_id)
        with open(path, "w") as f:
            json.dumps(session.to_dict(), indent=2, default=str)
            f.write(json.dumps(session.to_dict(), indent=2, default=str))

    def _load(self, session_id: str) -> SessionData | None:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return SessionData.from_dict(json.load(f))
        except (json.JSONDecodeError, KeyError):
            logger.warning("Corrupt session file: %s", path)
            return None

    def _is_expired(self, session: SessionData) -> bool:
        return (time.time() - session.last_active) > self._ttl_seconds

    def _cleanup_expired(self) -> int:
        """Remove expired sessions. Returns count removed."""
        expired = [
            sid for sid, s in self._active.items() if self._is_expired(s)
        ]
        for sid in expired:
            self.close_session(sid)
        return len(expired)
