"""Experience cache — two-tier lookup for repeated questions.

Tier 1: exact intent_hash  — O(1), identical question text.
Tier 2: semantic_hash      — O(1), same meaning but different phrasing.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from mcpdb.experience.fingerprint import (
    fingerprint_source, fingerprint_schema, intent_hash, semantic_hash,
)
from mcpdb.experience.records import CodeStep, SuccessRecord
from mcpdb.experience.store import ExperienceStore
from mcpdb.sources.base import SourceMetadata

logger = logging.getLogger("mcpdb.experience.cache")


class ExperienceCache:
    """Two-tier cache for repeated questions.

    Flow:
    1. Compute intent_hash (exact) and semantic_hash (normalized)
    2. Try exact match in memory → disk
    3. Try semantic match in memory → disk
    4. Verify schema hasn't drifted
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
        # Semantic index: semantic_hash → intent_hash (for O(1) fuzzy lookup)
        self._semantic_index: dict[str, str] = {}
        self._max_memory = 200

    # Mode hierarchy for mode-aware cache filtering
    _MODE_RANK = {
        "quick": 0,
        "simple": 1,
        "optimization_required": 2,
        "extended": 3,
        "deep": 4,
    }

    def lookup(
        self,
        question: str,
        source_metadata: SourceMetadata,
        mode_override: str | None = None,
    ) -> SuccessRecord | None:
        """Look up a cached response — exact match first, then semantic.

        Returns SuccessRecord if found and schema is still valid, else None.
        If mode_override is set, reject cached entries from a lower-tier mode.
        """
        fp = fingerprint_source(source_metadata)
        ih = intent_hash(question, fp)

        # --- Tier 1: exact match ---
        record = self._lookup_by_key(ih, fp, source_metadata)
        if record is not None:
            if self._mode_acceptable(record, mode_override):
                logger.debug("Cache hit (exact): %s", ih)
                return record
            logger.debug("Cache skip (mode too low): cached=%s, requested=%s",
                         record.query_mode, mode_override)

        # --- Tier 2: semantic match ---
        sh = semantic_hash(question, fp)
        mapped_ih = self._semantic_index.get(sh)
        if mapped_ih and mapped_ih != ih:
            record = self._lookup_by_key(mapped_ih, fp, source_metadata)
            if record is not None and self._mode_acceptable(record, mode_override):
                logger.info("Cache hit (semantic): %r → %s", question[:60], mapped_ih)
                return record

        # Check disk for semantic match
        record = self._store.find_by_semantic(fp, sh)
        if record is not None and self._is_valid(record, source_metadata):
            if self._mode_acceptable(record, mode_override):
                self._memory[record.intent_hash] = record
                self._semantic_index[sh] = record.intent_hash
                self._evict_memory_if_needed()
                logger.info("Cache hit (semantic/disk): %r → %s", question[:60], record.intent_hash)
                return record

        return None

    def _mode_acceptable(self, record: SuccessRecord, mode_override: str | None) -> bool:
        """Check if a cached record's mode is acceptable for the requested mode.

        When a specific mode is requested, reject cached entries from a lower-tier mode.
        """
        if mode_override is None:
            return True
        cached_rank = self._MODE_RANK.get(record.query_mode, 1)
        requested_rank = self._MODE_RANK.get(mode_override, 1)
        return cached_rank >= requested_rank

    def _lookup_by_key(
        self,
        ih: str,
        fp: str,
        source_metadata: SourceMetadata,
    ) -> SuccessRecord | None:
        """Look up by intent_hash in memory, then disk."""
        # Memory
        if ih in self._memory:
            record = self._memory[ih]
            if self._is_valid(record, source_metadata):
                return record
            del self._memory[ih]
            return None

        # Disk
        record = self._store.find_by_intent(fp, ih)
        if record is None:
            return None
        if not self._is_valid(record, source_metadata):
            return None

        # Promote to memory
        self._memory[ih] = record
        if record.semantic_hash:
            self._semantic_index[record.semantic_hash] = ih
        self._evict_memory_if_needed()
        return record

    def store(
        self,
        question: str,
        source_metadata: SourceMetadata,
        query_mode: str,
        steps: list[CodeStep],
        response: str,
        metadata: dict[str, Any] | None = None,
        plan_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a successful response in the cache."""
        fp = fingerprint_source(source_metadata)
        sh_schema = fingerprint_schema(source_metadata)
        ih = intent_hash(question, fp)
        sh = semantic_hash(question, fp)

        record = SuccessRecord(
            intent_hash=ih,
            question=question,
            source_fingerprint=fp,
            schema_hash=sh_schema,
            query_mode=query_mode,
            steps=steps,
            response=response,
            metadata=metadata or {},
            semantic_hash=sh,
            plan_metadata=plan_metadata or {},
        )

        self._store.store_success(record)
        self._memory[ih] = record
        self._semantic_index[sh] = ih
        self._evict_memory_if_needed()

        logger.debug("Cached response: %s (semantic: %s)", ih, sh)

    def invalidate(self, question: str, source_metadata: SourceMetadata) -> None:
        """Remove a cached entry (memory + semantic index)."""
        fp = fingerprint_source(source_metadata)
        ih = intent_hash(question, fp)
        sh = semantic_hash(question, fp)
        self._memory.pop(ih, None)
        self._semantic_index.pop(sh, None)

    def clear_source(self, source_metadata: SourceMetadata) -> None:
        """Clear all cache entries for a source (by metadata)."""
        fp = fingerprint_source(source_metadata)
        self.clear_source_by_fingerprint(fp)

    def clear_source_by_fingerprint(self, fp: str) -> None:
        """Clear all cache entries for a source fingerprint."""
        self._store.clear(fp)

        # Remove from memory
        to_remove = [
            k for k, v in self._memory.items()
            if v.source_fingerprint == fp
        ]
        for k in to_remove:
            del self._memory[k]

    def clear_all(self) -> None:
        """Clear all cache entries (memory + disk)."""
        for fp in self._store.list_fingerprints():
            self._store.clear(fp)
        self._memory.clear()
        self._semantic_index.clear()

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
