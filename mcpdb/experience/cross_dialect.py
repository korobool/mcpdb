"""Cross-dialect knowledge transfer — share patterns across sources of same type."""

from __future__ import annotations

import logging
from typing import Any

from mcpdb.experience.store import ExperienceStore

logger = logging.getLogger("mcpdb.experience.cross_dialect")


class CrossDialectKnowledge:
    """Share learned patterns across sources of the same database dialect.

    Patterns are promoted when confirmed by 2+ sources of the same type.
    """

    # In-memory pattern store: dialect → list of patterns
    _dialect_patterns: dict[str, list[dict[str, Any]]]

    def __init__(self, store: ExperienceStore, promotion_threshold: int = 2) -> None:
        self._store = store
        self._promotion_threshold = promotion_threshold
        self._dialect_patterns = {}
        # Track which sources contributed patterns: dialect → pattern_key → set of fingerprints
        self._contributions: dict[str, dict[str, set[str]]] = {}

    def record_pattern(
        self,
        dialect: str,
        source_fingerprint: str,
        pattern_key: str,
        pattern_description: str,
        category: str = "general",
    ) -> None:
        """Record a dialect pattern observed in a source.

        Pattern is promoted to shared knowledge when seen in enough sources.
        """
        dialect = dialect.lower()

        # Track contributions
        if dialect not in self._contributions:
            self._contributions[dialect] = {}
        if pattern_key not in self._contributions[dialect]:
            self._contributions[dialect][pattern_key] = set()

        self._contributions[dialect][pattern_key].add(source_fingerprint)

        # Promote if threshold met
        if len(self._contributions[dialect][pattern_key]) >= self._promotion_threshold:
            self._promote_pattern(dialect, pattern_key, pattern_description, category)

    def _promote_pattern(
        self,
        dialect: str,
        pattern_key: str,
        description: str,
        category: str,
    ) -> None:
        """Promote a pattern to shared knowledge."""
        if dialect not in self._dialect_patterns:
            self._dialect_patterns[dialect] = []

        # Check if already promoted
        for p in self._dialect_patterns[dialect]:
            if p["key"] == pattern_key:
                return

        pattern = {
            "key": pattern_key,
            "description": description,
            "category": category,
            "source_count": len(self._contributions.get(dialect, {}).get(pattern_key, set())),
        }
        self._dialect_patterns[dialect].append(pattern)
        logger.info(
            "Promoted pattern '%s' for dialect %s (confirmed by %d sources)",
            pattern_key,
            dialect,
            pattern["source_count"],
        )

    def get_patterns(self, dialect: str) -> list[dict[str, Any]]:
        """Get all promoted patterns for a dialect."""
        return list(self._dialect_patterns.get(dialect.lower(), []))

    def get_pattern_context(self, dialect: str) -> str | None:
        """Get patterns as a context string for LLM injection."""
        patterns = self.get_patterns(dialect)
        if not patterns:
            return None

        lines = [f"Known patterns for {dialect} databases:"]
        for p in patterns:
            lines.append(f"- {p['description']} (confirmed by {p['source_count']} sources)")
        return "\n".join(lines)

    def get_all_dialects(self) -> list[str]:
        """List all dialects with patterns."""
        return list(self._dialect_patterns.keys())

    def get_stats(self) -> dict[str, Any]:
        """Get cross-dialect knowledge statistics."""
        return {
            "dialects": len(self._dialect_patterns),
            "total_patterns": sum(
                len(pats) for pats in self._dialect_patterns.values()
            ),
            "pending_patterns": sum(
                sum(
                    1
                    for fps in pats.values()
                    if len(fps) < self._promotion_threshold
                )
                for pats in self._contributions.values()
            ),
        }
