"""Source fingerprinting — stable identity hash per data source."""

from __future__ import annotations

import hashlib
from typing import Any

from mcpdb.sources.base import SourceMetadata


def fingerprint_source(metadata: SourceMetadata) -> str:
    """Generate a stable fingerprint for a data source.

    The fingerprint is based on source type + table names + column signatures,
    so that two connections to the same database produce the same fingerprint
    even if made at different times.
    """
    parts = [metadata.source_type.value]

    # Sort tables for determinism
    for table in sorted(metadata.tables, key=lambda t: t.name):
        col_sig = ",".join(
            f"{c.name}:{c.dtype}" for c in sorted(table.columns, key=lambda c: c.name)
        )
        parts.append(f"{table.name}({col_sig})")

    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def fingerprint_schema(metadata: SourceMetadata) -> str:
    """Generate a shorter schema hash for drift detection.

    Changes to table structure will change this hash.
    """
    parts = []
    for table in sorted(metadata.tables, key=lambda t: t.name):
        cols = ",".join(
            f"{c.name}:{c.dtype}" for c in sorted(table.columns, key=lambda c: c.name)
        )
        parts.append(f"{table.name}:{cols}")
    raw = "|".join(parts)
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def intent_hash(question: str, source_fingerprint: str) -> str:
    """Hash a question + source fingerprint for exact-match cache lookup."""
    normalized = question.strip().lower()
    raw = f"{normalized}|{source_fingerprint}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]
