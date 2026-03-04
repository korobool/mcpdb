"""Strategy records — remember which cost gate strategies worked."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from mcpdb.experience.fingerprint import fingerprint_source
from mcpdb.experience.store import ExperienceStore
from mcpdb.sources.base import SourceMetadata

logger = logging.getLogger("mcpdb.experience.strategy")


@dataclass
class StrategyRecord:
    """A record of a cost gate strategy outcome."""

    source_fingerprint: str
    query_pattern: str  # simplified query pattern
    estimated_rows: int
    strategy: str  # "SAMPLE", "FULL"
    success: bool
    result_quality: str = "unknown"  # "good", "approximate", "poor", "unknown"
    time_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "strategy",
            "source_fingerprint": self.source_fingerprint,
            "query_pattern": self.query_pattern,
            "estimated_rows": self.estimated_rows,
            "strategy": self.strategy,
            "success": self.success,
            "result_quality": self.result_quality,
            "time_ms": self.time_ms,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StrategyRecord:
        return cls(
            source_fingerprint=d["source_fingerprint"],
            query_pattern=d["query_pattern"],
            estimated_rows=d.get("estimated_rows", 0),
            strategy=d["strategy"],
            success=d["success"],
            result_quality=d.get("result_quality", "unknown"),
            time_ms=d.get("time_ms", 0.0),
            timestamp=d.get("timestamp", 0.0),
        )


class StrategyTracker:
    """Track and suggest cost gate strategies based on past experience."""

    def __init__(self, store: ExperienceStore) -> None:
        self._store = store

    def record_strategy(
        self,
        source_metadata: SourceMetadata,
        query_pattern: str,
        estimated_rows: int,
        strategy: str,
        success: bool,
        result_quality: str = "unknown",
        time_ms: float = 0.0,
    ) -> None:
        """Record a strategy outcome."""
        fp = fingerprint_source(source_metadata)
        record = StrategyRecord(
            source_fingerprint=fp,
            query_pattern=query_pattern,
            estimated_rows=estimated_rows,
            strategy=strategy,
            success=success,
            result_quality=result_quality,
            time_ms=time_ms,
        )
        # Store as a JSONL record via a separate file
        import json
        from pathlib import Path

        path = Path(self._store._storage_dir) / f"{fp}_strategies.jsonl"
        with self._store._lock:
            with open(path, "a") as f:
                f.write(json.dumps(record.to_dict()) + "\n")

    def get_strategy_records(
        self, source_metadata: SourceMetadata
    ) -> list[StrategyRecord]:
        """Get all strategy records for a source."""
        import json
        from pathlib import Path

        fp = fingerprint_source(source_metadata)
        path = Path(self._store._storage_dir) / f"{fp}_strategies.jsonl"
        if not path.exists():
            return []

        records = []
        with self._store._lock:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(StrategyRecord.from_dict(json.loads(line)))
                        except (json.JSONDecodeError, KeyError):
                            pass
        return records

    def suggest_strategy(
        self,
        source_metadata: SourceMetadata,
        query_pattern: str,
        estimated_rows: int,
    ) -> str | None:
        """Suggest a strategy based on past experience.

        Returns "SAMPLE" or "FULL" if there's a strong signal, else None.
        """
        records = self.get_strategy_records(source_metadata)
        if not records:
            return None

        # Find records with similar patterns and row counts
        relevant = []
        for rec in records:
            if not rec.success:
                continue
            # Pattern similarity: exact match or same estimated row magnitude
            pattern_match = rec.query_pattern == query_pattern
            row_magnitude_match = (
                _row_magnitude(rec.estimated_rows) == _row_magnitude(estimated_rows)
            )
            if pattern_match or row_magnitude_match:
                relevant.append(rec)

        if not relevant:
            return None

        # Count successful strategies
        strategy_counts: dict[str, int] = {}
        quality_scores: dict[str, list[str]] = {}
        for rec in relevant:
            strategy_counts[rec.strategy] = strategy_counts.get(rec.strategy, 0) + 1
            quality_scores.setdefault(rec.strategy, []).append(rec.result_quality)

        # Need at least 2 records to suggest
        best_strategy = max(strategy_counts, key=lambda k: strategy_counts[k])
        if strategy_counts[best_strategy] < 2:
            return None

        # Check quality — don't suggest if mostly poor
        qualities = quality_scores.get(best_strategy, [])
        poor_count = sum(1 for q in qualities if q == "poor")
        if poor_count > len(qualities) // 2:
            return None

        return best_strategy

    def get_strategy_context(
        self,
        source_metadata: SourceMetadata,
        query_pattern: str,
        estimated_rows: int,
    ) -> str | None:
        """Get a context string about past strategy outcomes for LLM injection."""
        suggestion = self.suggest_strategy(source_metadata, query_pattern, estimated_rows)
        if suggestion is None:
            return None

        records = self.get_strategy_records(source_metadata)
        relevant_count = sum(
            1 for r in records
            if r.success and r.strategy == suggestion
        )

        return (
            f"Based on {relevant_count} previous similar queries, "
            f"the '{suggestion}' strategy has worked well for this type of query."
        )


def _row_magnitude(rows: int) -> str:
    """Classify row count into magnitude buckets."""
    if rows < 1_000:
        return "small"
    elif rows < 100_000:
        return "medium"
    elif rows < 10_000_000:
        return "large"
    else:
        return "very_large"
