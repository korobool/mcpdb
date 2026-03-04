"""Schema drift detection — detect and handle schema changes between sessions."""

from __future__ import annotations

import logging
from typing import Any

from mcpdb.experience.fingerprint import fingerprint_schema, fingerprint_source
from mcpdb.experience.store import ExperienceStore
from mcpdb.sources.base import SourceMetadata

logger = logging.getLogger("mcpdb.experience.schema_drift")


class SchemaDriftDetector:
    """Detect schema changes and invalidate affected cache entries.

    Stores the last known schema hash per source. On reconnection,
    compares current schema hash to stored hash.
    """

    def __init__(self, store: ExperienceStore) -> None:
        self._store = store
        # In-memory: source_fingerprint → last known schema_hash
        self._known_schemas: dict[str, str] = {}

    def register_schema(self, source_metadata: SourceMetadata) -> None:
        """Register the current schema for a source."""
        sid = source_metadata.source_id
        sh = fingerprint_schema(source_metadata)
        self._known_schemas[sid] = sh

    def check_drift(self, source_metadata: SourceMetadata) -> DriftResult:
        """Check if schema has drifted since last registration.

        Returns a DriftResult with details about any changes detected.
        """
        sid = source_metadata.source_id
        current_sh = fingerprint_schema(source_metadata)
        previous_sh = self._known_schemas.get(sid)

        if previous_sh is None:
            # First time seeing this source
            self._known_schemas[sid] = current_sh
            return DriftResult(drifted=False, is_new=True)

        if current_sh == previous_sh:
            return DriftResult(drifted=False, is_new=False)

        # Drift detected
        self._known_schemas[sid] = current_sh
        logger.warning(
            "Schema drift detected for source %s: %s -> %s",
            sid,
            previous_sh,
            current_sh,
        )
        return DriftResult(
            drifted=True,
            is_new=False,
            previous_hash=previous_sh,
            current_hash=current_sh,
        )

    def handle_drift(
        self,
        source_metadata: SourceMetadata,
        invalidate_cache: bool = True,
    ) -> int:
        """Handle schema drift by invalidating affected cache entries.

        Returns number of invalidated records.
        """
        fp = fingerprint_source(source_metadata)

        if not invalidate_cache:
            return 0

        # Get all success records and count affected
        successes = self._store.get_successes(fp)
        current_sh = fingerprint_schema(source_metadata)

        affected = sum(1 for r in successes if r.schema_hash != current_sh)

        if affected > 0:
            logger.info(
                "Invalidating %d cached records due to schema drift for %s",
                affected,
                fp,
            )
            # Clear the entire source's cache — simpler than selective invalidation
            self._store.clear(fp)

        return affected

    def get_known_schemas(self) -> dict[str, str]:
        """Get all known schema hashes."""
        return dict(self._known_schemas)


class DriftResult:
    """Result of a schema drift check."""

    def __init__(
        self,
        drifted: bool,
        is_new: bool = False,
        previous_hash: str = "",
        current_hash: str = "",
    ) -> None:
        self.drifted = drifted
        self.is_new = is_new
        self.previous_hash = previous_hash
        self.current_hash = current_hash

    def __bool__(self) -> bool:
        """True if drift was detected."""
        return self.drifted

    def __repr__(self) -> str:
        if self.is_new:
            return "DriftResult(new_source)"
        if self.drifted:
            return f"DriftResult(drifted: {self.previous_hash} -> {self.current_hash})"
        return "DriftResult(no_drift)"
