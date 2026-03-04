"""Anti-pattern tracking — learn from repeated failures."""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from mcpdb.experience.records import FailureRecord
from mcpdb.experience.store import ExperienceStore
from mcpdb.sources.base import SourceMetadata

logger = logging.getLogger("mcpdb.experience.antipatterns")


class AntiPatternTracker:
    """Track repeated failures and provide avoidance hints.

    When the same error pattern occurs >= min_occurrences times,
    it becomes an anti-pattern that gets injected into planning prompts.
    """

    def __init__(
        self,
        store: ExperienceStore,
        min_occurrences: int = 2,
    ) -> None:
        self._store = store
        self._min_occurrences = min_occurrences

    def record_failure(
        self,
        question: str,
        source_metadata: SourceMetadata,
        error_type: str,
        error_message: str,
        failed_code: str = "",
    ) -> None:
        """Record a failure for anti-pattern tracking."""
        from mcpdb.experience.fingerprint import fingerprint_source

        fp = fingerprint_source(source_metadata)
        record = FailureRecord(
            question=question,
            source_fingerprint=fp,
            error_type=error_type,
            error_message=error_message,
            failed_code=failed_code,
        )
        self._store.store_failure(record)

    def get_anti_patterns(
        self,
        source_metadata: SourceMetadata,
    ) -> list[dict[str, Any]]:
        """Get promoted anti-patterns for a source.

        Returns patterns that have occurred >= min_occurrences times.
        """
        from mcpdb.experience.fingerprint import fingerprint_source

        fp = fingerprint_source(source_metadata)
        failures = self._store.get_failures(fp)

        if not failures:
            return []

        # Group by error_type + simplified error_message
        pattern_counts: Counter[str] = Counter()
        pattern_examples: dict[str, FailureRecord] = {}

        for f in failures:
            key = f"{f.error_type}:{_simplify_error(f.error_message)}"
            pattern_counts[key] += 1
            pattern_examples[key] = f

        # Promote patterns with enough occurrences
        anti_patterns = []
        for key, count in pattern_counts.items():
            if count >= self._min_occurrences:
                example = pattern_examples[key]
                anti_patterns.append({
                    "error_type": example.error_type,
                    "error_pattern": _simplify_error(example.error_message),
                    "occurrences": count,
                    "example_code": example.failed_code[:200] if example.failed_code else "",
                    "avoidance_hint": _generate_hint(example),
                })

        return anti_patterns

    def get_anti_pattern_context(
        self,
        source_metadata: SourceMetadata,
    ) -> str | None:
        """Get anti-pattern context string for planning prompt injection.

        Returns formatted string or None if no anti-patterns found.
        """
        patterns = self.get_anti_patterns(source_metadata)
        if not patterns:
            return None

        lines = ["## Known Anti-Patterns (avoid these mistakes)"]
        for p in patterns:
            lines.append(
                f"- {p['error_type']}: {p['error_pattern']} "
                f"(occurred {p['occurrences']} times)"
            )
            if p["avoidance_hint"]:
                lines.append(f"  Hint: {p['avoidance_hint']}")
            if p["example_code"]:
                lines.append(f"  Failed code: `{p['example_code']}`")

        return "\n".join(lines)


def _simplify_error(message: str) -> str:
    """Simplify an error message to a pattern key.

    Removes specific identifiers to group similar errors.
    """
    import re
    # Remove quoted strings
    simplified = re.sub(r"'[^']*'", "'...'", message)
    # Remove specific numbers
    simplified = re.sub(r"\b\d+\b", "N", simplified)
    # Truncate
    return simplified[:100]


def _generate_hint(record: FailureRecord) -> str:
    """Generate a basic avoidance hint from a failure record."""
    error_lower = record.error_message.lower()

    if "column" in error_lower and "not found" in error_lower:
        return "Check column names against the schema before using them."
    if "table" in error_lower and "not found" in error_lower:
        return "Verify table names exist in the schema."
    if "syntax" in error_lower:
        return "Check SQL syntax carefully."
    if "permission" in error_lower or "denied" in error_lower:
        return "This operation may require elevated permissions."
    if "timeout" in error_lower:
        return "Consider adding LIMIT or using a sampling strategy."
    if "memory" in error_lower or "oom" in error_lower:
        return "Reduce result set size or use aggregation."
    if "type" in error_lower and ("mismatch" in error_lower or "cast" in error_lower):
        return "Check data types; explicit CAST may be needed."

    return "Review the error pattern and adjust the approach."
