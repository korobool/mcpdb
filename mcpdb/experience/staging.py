"""Staging store — holds results pending async quality evaluation.

Part of the async quality evaluation pipeline:

    Agent result → _is_cacheable() gate → StagingStore (JSONL on disk)
                                               ↓
                                    QualityWorker polls every 30s
                                               ↓
                                    QualityEvaluator (LLM scoring)
                                               ↓
                                    promote → ExperienceCache
                                    reject  → FailureRecord (anti-pattern)

Storage location: ~/.mcpdb/experience/staging/{fingerprint}.jsonl
Each source gets its own JSONL file. Records are append-only until
evaluated, then removed (promoted or rejected).

The staging store is file-based (not an in-process queue) because it
must work across process boundaries: CLI/MCP write staged records,
Playground's background worker or `mcpdb experience eval` evaluates
them later.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from mcpdb.experience.records import StagedRecord

logger = logging.getLogger("mcpdb.experience.staging")


class StagingStore:
    """JSONL-based staging area for results awaiting quality evaluation.

    Each source gets its own JSONL file: {staging_dir}/{fingerprint}.jsonl
    Records are append-only; evaluated records are removed or promoted.
    """

    def __init__(
        self,
        staging_dir: str = "~/.mcpdb/experience/staging",
    ) -> None:
        self._staging_dir = Path(os.path.expanduser(staging_dir))
        self._lock = threading.Lock()
        self._staging_dir.mkdir(parents=True, exist_ok=True)

    def _source_path(self, fingerprint: str) -> Path:
        return self._staging_dir / f"{fingerprint}.jsonl"

    def stage(self, record: StagedRecord) -> None:
        """Append a staged record for later evaluation."""
        path = self._source_path(record.source_fingerprint)
        with self._lock:
            with open(path, "a") as f:
                f.write(json.dumps(record.to_dict()) + "\n")
        logger.debug("Staged record: %s (fp=%s)", record.intent_hash, record.source_fingerprint)

    def get_pending(self, fingerprint: str) -> list[StagedRecord]:
        """Load all unevaluated staged records for a source."""
        return [
            r for r in self._load_all(fingerprint)
            if not r.evaluated
        ]

    def get_all(self, fingerprint: str) -> list[StagedRecord]:
        """Load all staged records for a source."""
        return self._load_all(fingerprint)

    def mark_evaluated(self, fingerprint: str, intent_hash: str) -> None:
        """Mark a staged record as evaluated (sets evaluated=True)."""
        records = self._load_raw(fingerprint)
        changed = False
        for r in records:
            if r.get("intent_hash") == intent_hash and not r.get("evaluated"):
                r["evaluated"] = True
                changed = True
                break

        if changed:
            self._rewrite(fingerprint, records)

    def remove(self, fingerprint: str, intent_hash: str) -> None:
        """Remove a staged record after promotion or rejection."""
        records = self._load_raw(fingerprint)
        filtered = [r for r in records if r.get("intent_hash") != intent_hash]

        if len(filtered) < len(records):
            self._rewrite(fingerprint, filtered)

    def list_fingerprints(self) -> list[str]:
        """List all source fingerprints with staged records."""
        return [p.stem for p in self._staging_dir.glob("*.jsonl")]

    def get_all_pending(self) -> list[StagedRecord]:
        """Get all pending records across all sources."""
        pending = []
        for fp in self.list_fingerprints():
            pending.extend(self.get_pending(fp))
        return pending

    def _load_all(self, fingerprint: str) -> list[StagedRecord]:
        """Load all staged records from a source's JSONL file."""
        return [
            StagedRecord.from_dict(r)
            for r in self._load_raw(fingerprint)
            if r.get("type") == "staged"
        ]

    def _load_raw(self, fingerprint: str) -> list[dict[str, Any]]:
        """Load raw dicts from a source's JSONL file."""
        path = self._source_path(fingerprint)
        if not path.exists():
            return []

        records: list[dict[str, Any]] = []
        with self._lock:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            logger.warning("Skipping corrupt staged record in %s", path)
        return records

    def _rewrite(self, fingerprint: str, records: list[dict[str, Any]]) -> None:
        """Rewrite a source's JSONL file with updated records."""
        path = self._source_path(fingerprint)
        with self._lock:
            if not records:
                if path.exists():
                    path.unlink()
                return
            with open(path, "w") as f:
                for r in records:
                    f.write(json.dumps(r) + "\n")
