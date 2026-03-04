"""Template retriever — semantic search for similar past experiences."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from mcpdb.experience.embeddings import weighted_similarity
from mcpdb.experience.records import SuccessRecord
from mcpdb.experience.store import ExperienceStore
from mcpdb.sources.base import SourceMetadata

logger = logging.getLogger("mcpdb.experience.retriever")


@dataclass
class RetrievalResult:
    """A retrieved experience template with similarity score."""

    record: SuccessRecord
    similarity: float
    match_type: str  # "template" (high) or "hint" (medium)


class TemplateRetriever:
    """Retrieve similar past experiences for planning assistance.

    Uses Jaccard word-overlap similarity with table-name boosting.
    High similarity (>threshold_high) → inject as template
    Medium similarity (>threshold_medium) → inject as hint
    """

    def __init__(
        self,
        store: ExperienceStore,
        threshold_high: float = 0.85,
        threshold_medium: float = 0.65,
    ) -> None:
        self._store = store
        self._threshold_high = threshold_high
        self._threshold_medium = threshold_medium

    def retrieve(
        self,
        question: str,
        source_metadata: SourceMetadata,
        max_results: int = 3,
    ) -> list[RetrievalResult]:
        """Find similar past experiences for a question.

        Returns up to max_results matches sorted by similarity (highest first).
        """
        from mcpdb.experience.fingerprint import fingerprint_source

        fp = fingerprint_source(source_metadata)
        records = self._store.get_successes(fp)

        if not records:
            return []

        # Extract table names from the question for boosting
        question_tables = self._extract_table_references(question, source_metadata)

        results: list[RetrievalResult] = []
        for record in records:
            record_tables = self._extract_table_references(
                record.question, source_metadata
            )

            sim = weighted_similarity(
                question, record.question,
                table_names_a=question_tables,
                table_names_b=record_tables,
            )

            if sim >= self._threshold_high:
                results.append(RetrievalResult(
                    record=record, similarity=sim, match_type="template",
                ))
            elif sim >= self._threshold_medium:
                results.append(RetrievalResult(
                    record=record, similarity=sim, match_type="hint",
                ))

        # Sort by similarity descending
        results.sort(key=lambda r: r.similarity, reverse=True)
        return results[:max_results]

    def get_template_context(
        self,
        question: str,
        source_metadata: SourceMetadata,
    ) -> str | None:
        """Get template context string for injection into planning prompt.

        Returns a formatted string or None if no relevant templates found.
        """
        results = self.retrieve(question, source_metadata, max_results=1)
        if not results:
            return None

        best = results[0]
        if best.match_type == "template":
            steps_desc = "\n".join(
                f"  {i+1}. [{s.action_type}] {s.code[:200]}"
                for i, s in enumerate(best.record.steps)
            )
            return (
                f"## Similar Successful Approach (similarity: {best.similarity:.0%})\n"
                f"Question: {best.record.question}\n"
                f"Mode: {best.record.query_mode}\n"
                f"Steps:\n{steps_desc}\n"
                f"Use this as a template and adapt for the current question."
            )
        elif best.match_type == "hint":
            return (
                f"## Related Past Query (similarity: {best.similarity:.0%})\n"
                f"A similar question was answered using {best.record.query_mode} mode "
                f"with {len(best.record.steps)} step(s). "
                f"Consider a similar approach."
            )

        return None

    def _extract_table_references(
        self, text: str, source_metadata: SourceMetadata,
    ) -> set[str]:
        """Extract table name references from text."""
        text_lower = text.lower()
        found = set()
        for table in source_metadata.tables:
            # Check exact name and common variations
            name_lower = table.name.lower()
            if name_lower in text_lower:
                found.add(name_lower)
            # Also check without underscores (e.g., "customer orders" → "customer_orders")
            name_spaces = name_lower.replace("_", " ")
            if name_spaces in text_lower:
                found.add(name_lower)
        return found
