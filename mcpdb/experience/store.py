"""Experience store — JSONL-based per-source persistent storage."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from mcpdb.experience.records import FailureRecord, SuccessRecord

logger = logging.getLogger("mcpdb.experience.store")


class ExperienceStore:
    """JSONL-based storage for experience records, keyed by source fingerprint.

    Each source gets its own JSONL file: {storage_dir}/{fingerprint}.jsonl
    Records are append-only; eviction happens during compaction.
    """

    def __init__(
        self,
        storage_dir: str = "~/.mcpdb/experience",
        max_success: int = 2000,
        max_failure: int = 500,
    ) -> None:
        self._storage_dir = Path(os.path.expanduser(storage_dir))
        self._max_success = max_success
        self._max_failure = max_failure
        self._lock = threading.Lock()

        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _source_path(self, fingerprint: str) -> Path:
        return self._storage_dir / f"{fingerprint}.jsonl"

    def store_success(self, record: SuccessRecord) -> None:
        """Append a success record."""
        path = self._source_path(record.source_fingerprint)
        with self._lock:
            with open(path, "a") as f:
                f.write(json.dumps(record.to_dict()) + "\n")

    def store_failure(self, record: FailureRecord) -> None:
        """Append a failure record."""
        path = self._source_path(record.source_fingerprint)
        with self._lock:
            with open(path, "a") as f:
                f.write(json.dumps(record.to_dict()) + "\n")

    def get_successes(self, fingerprint: str) -> list[SuccessRecord]:
        """Load all success records for a source."""
        return [
            SuccessRecord.from_dict(r)
            for r in self._load_records(fingerprint)
            if r.get("type") == "success"
        ]

    def get_failures(self, fingerprint: str) -> list[FailureRecord]:
        """Load all failure records for a source."""
        return [
            FailureRecord.from_dict(r)
            for r in self._load_records(fingerprint)
            if r.get("type") == "failure"
        ]

    def find_by_intent(
        self, fingerprint: str, intent_hash: str
    ) -> SuccessRecord | None:
        """Find a cached success record by intent hash (exact match)."""
        for record in self.get_successes(fingerprint):
            if record.intent_hash == intent_hash:
                return record
        return None

    def _load_records(self, fingerprint: str) -> list[dict[str, Any]]:
        """Load all records from a source's JSONL file."""
        path = self._source_path(fingerprint)
        if not path.exists():
            return []

        records = []
        with self._lock:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            logger.warning("Skipping corrupt record in %s", path)
        return records

    def compact(self, fingerprint: str) -> int:
        """Compact a source's store, evicting old records beyond limits.

        Returns number of records removed.
        """
        path = self._source_path(fingerprint)
        if not path.exists():
            return 0

        records = self._load_records(fingerprint)
        successes = [r for r in records if r.get("type") == "success"]
        failures = [r for r in records if r.get("type") == "failure"]

        # Sort by timestamp (newest first) and trim
        successes.sort(key=lambda r: r.get("timestamp", 0), reverse=True)
        failures.sort(key=lambda r: r.get("timestamp", 0), reverse=True)

        trimmed_s = successes[: self._max_success]
        trimmed_f = failures[: self._max_failure]

        removed = (len(successes) - len(trimmed_s)) + (len(failures) - len(trimmed_f))

        if removed > 0:
            with self._lock:
                with open(path, "w") as f:
                    for r in trimmed_s + trimmed_f:
                        f.write(json.dumps(r) + "\n")
            logger.info("Compacted %s: removed %d records", fingerprint, removed)

        return removed

    def clear(self, fingerprint: str) -> None:
        """Delete all records for a source."""
        path = self._source_path(fingerprint)
        with self._lock:
            if path.exists():
                path.unlink()

    def list_fingerprints(self) -> list[str]:
        """List all source fingerprints with stored records."""
        return [
            p.stem for p in self._storage_dir.glob("*.jsonl")
        ]

    def get_stats(self, fingerprint: str) -> dict[str, Any]:
        """Get statistics for a source's experience store."""
        records = self._load_records(fingerprint)
        successes = [r for r in records if r.get("type") == "success"]
        failures = [r for r in records if r.get("type") == "failure"]
        return {
            "fingerprint": fingerprint,
            "total_records": len(records),
            "successes": len(successes),
            "failures": len(failures),
            "oldest": min((r.get("timestamp", 0) for r in records), default=0),
            "newest": max((r.get("timestamp", 0) for r in records), default=0),
        }
