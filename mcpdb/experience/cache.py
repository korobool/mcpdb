"""Experience cache — exact-match O(1) lookup for repeated questions."""

from __future__ import annotations

import logging
import time
from typing import Any

from mcpdb.experience.fingerprint import fingerprint_source, fingerprint_schema, intent_hash
from mcpdb.experience.records import CodeStep, SuccessRecord
from mcpdb.experience.store import ExperienceStore
from mcpdb.sources.base import SourceMetadata

logger = logging.getLogger("mcpdb.experience.cache")


class ExperienceCache:
    """Exact-match cache for repeated questions.

    Flow:
    1. On query: compute intent_hash(question, source_fingerprint)
    2. Check in-memory cache (O(1))
    3. If miss, check persistent store
    4. If hit, verify schema hasn't drifted
    5. Return cached response or None
    """

    def __init__(
        self,
        store: ExperienceStore,
        max_age_days: int = 30,
    ) -> None:
        self._store = store
        self._max_age_seconds = max_age_days * 86400

        # In-memory LRU-ish cache: intent_hash → SuccessRecord
        self._memory: dict[str, SuccessRecord] = {}
        self._max_memory = 200

    def lookup(
        self,
        question: str,
        source_metadata: SourceMetadata,
    ) -> SuccessRecord | None:
        """Look up a cached response for an exact question match.

        Returns SuccessRecord if found and schema is still valid, else None.
        """
        fp = fingerprint_source(source_metadata)
        ih = intent_hash(question, fp)

        # Check in-memory first
        if ih in self._memory:
            record = self._memory[ih]
            if self._is_valid(record, source_metadata):
                logger.debug("Cache hit (memory): %s", ih)
                return record
            else:
                del self._memory[ih]
                return None

        # Check persistent store
        record = self._store.find_by_intent(fp, ih)
        if record is None:
            return None

        if not self._is_valid(record, source_metadata):
            logger.info("Cache hit but schema drifted: %s", ih)
            return None

        # Promote to memory cache
        self._memory[ih] = record
        self._evict_memory_if_needed()

        logger.debug("Cache hit (disk): %s", ih)
        return record

    def store(
        self,
        question: str,
        source_metadata: SourceMetadata,
        query_mode: str,
        steps: list[CodeStep],
        response: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a successful response in the cache."""
        fp = fingerprint_source(source_metadata)
        sh = fingerprint_schema(source_metadata)
        ih = intent_hash(question, fp)

        record = SuccessRecord(
            intent_hash=ih,
            question=question,
            source_fingerprint=fp,
            schema_hash=sh,
            query_mode=query_mode,
            steps=steps,
            response=response,
            metadata=metadata or {},
        )

        self._store.store_success(record)
        self._memory[ih] = record
        self._evict_memory_if_needed()

        logger.debug("Cached response: %s", ih)

    def invalidate(self, question: str, source_metadata: SourceMetadata) -> None:
        """Remove a cached entry."""
        fp = fingerprint_source(source_metadata)
        ih = intent_hash(question, fp)
        self._memory.pop(ih, None)

    def clear_source(self, source_metadata: SourceMetadata) -> None:
        """Clear all cache entries for a source."""
        fp = fingerprint_source(source_metadata)
        self._store.clear(fp)

        # Remove from memory
        to_remove = [
            k for k, v in self._memory.items()
            if v.source_fingerprint == fp
        ]
        for k in to_remove:
            del self._memory[k]

    def get_stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        fingerprints = self._store.list_fingerprints()
        total_records = 0
        for fp in fingerprints:
            stats = self._store.get_stats(fp)
            total_records += stats["successes"]

        return {
            "memory_entries": len(self._memory),
            "memory_max": self._max_memory,
            "disk_sources": len(fingerprints),
            "disk_total_successes": total_records,
        }

    def _is_valid(self, record: SuccessRecord, source_metadata: SourceMetadata) -> bool:
        """Check if a cached record is still valid."""
        # Check age
        age = time.time() - record.timestamp
        if age > self._max_age_seconds:
            return False

        # Check schema drift
        current_sh = fingerprint_schema(source_metadata)
        if record.schema_hash != current_sh:
            return False

        return True

    def _evict_memory_if_needed(self) -> None:
        """Evict oldest entries if memory cache is full."""
        if len(self._memory) <= self._max_memory:
            return

        # Remove oldest by timestamp
        sorted_entries = sorted(
            self._memory.items(),
            key=lambda kv: kv[1].timestamp,
        )
        to_remove = len(self._memory) - self._max_memory
        for key, _ in sorted_entries[:to_remove]:
            del self._memory[key]
