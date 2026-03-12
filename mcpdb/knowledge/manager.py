"""Knowledge manager — central coordinator for all knowledge providers."""

from __future__ import annotations

import logging
from typing import Any

from mcpdb.knowledge.base import KnowledgeCategory, KnowledgeChunk
from mcpdb.knowledge.retriever import format_knowledge_context
from mcpdb.knowledge.file_provider import FileKnowledgeProvider

logger = logging.getLogger("mcpdb.knowledge")

# Per-injection-point category routing
INJECTION_CATEGORIES: dict[str, set[KnowledgeCategory] | None] = {
    "classify": {KnowledgeCategory.TERMINOLOGY, KnowledgeCategory.SCHEMA_DOCS},
    "plan": {
        KnowledgeCategory.QUERY_TEMPLATE,
        KnowledgeCategory.BUSINESS_RULE,
        KnowledgeCategory.DATA_QUALITY,
        KnowledgeCategory.SCHEMA_DOCS,
        KnowledgeCategory.VISUALIZATION,
    },
    "debug": {
        KnowledgeCategory.DATA_QUALITY,
        KnowledgeCategory.SCHEMA_DOCS,
        KnowledgeCategory.QUERY_TEMPLATE,
    },
    "synthesize": {
        KnowledgeCategory.BUSINESS_RULE,
        KnowledgeCategory.TERMINOLOGY,
        KnowledgeCategory.VISUALIZATION,
    },
    "blueprint": None,  # all categories (deep mode)
}

INJECTION_BUDGETS: dict[str, int] = {
    "classify": 500,
    "plan": 2000,
    "debug": 1000,
    "synthesize": 1000,
    "blueprint": 2000,
}


class KnowledgeManager:
    """Aggregates knowledge from multiple providers.

    Usage:
        mgr = KnowledgeManager()
        mgr.add_file_provider(FileKnowledgeProvider(["/path/to/rag/"]))
        mgr.load()
        context = mgr.retrieve("What's the P90 cost?", injection_point="plan")
    """

    def __init__(self) -> None:
        self._file_providers: list[FileKnowledgeProvider] = []
        self._loaded: bool = False

    def add_file_provider(self, provider: FileKnowledgeProvider) -> None:
        """Register a file-based knowledge provider."""
        self._file_providers.append(provider)

    def load(self) -> int:
        """Load all providers. Returns total chunk count."""
        total = 0
        for fp in self._file_providers:
            count = fp.load()
            total += count

        self._loaded = True
        if total > 0:
            logger.info("Knowledge loaded: %d total chunks from %d providers",
                        total, len(self._file_providers))
        return total

    def retrieve(
        self,
        query: str,
        *,
        injection_point: str = "plan",
        categories: set[KnowledgeCategory] | None = None,
        max_tokens: int | None = None,
        max_chunks: int = 10,
        table_names: list[str] | None = None,
    ) -> str:
        """Retrieve and format relevant knowledge for prompt injection.

        Args:
            query: The user's question or search query.
            injection_point: Where in the pipeline this will be injected.
                             Determines default categories and token budget.
            categories: Override category filter (if None, uses injection_point defaults).
            max_tokens: Override token budget (if None, uses injection_point defaults).
            max_chunks: Maximum number of chunks to consider.
            table_names: Optional table names for relevance boosting.

        Returns:
            Formatted knowledge string ready for prompt injection.
            Empty string if no knowledge available or no relevant chunks found.
        """
        if not self._loaded or not self._file_providers:
            return ""

        # Resolve categories and budget from injection point
        if categories is None:
            categories = INJECTION_CATEGORIES.get(injection_point)
        if max_tokens is None:
            max_tokens = INJECTION_BUDGETS.get(injection_point, 2000)

        # Collect chunks from all providers
        all_chunks: list[KnowledgeChunk] = []
        for provider in self._file_providers:
            chunks = provider.retrieve(
                query,
                categories=categories,
                max_chunks=max_chunks,
                table_names=table_names,
            )
            all_chunks.extend(chunks)

        if not all_chunks:
            logger.debug("No knowledge chunks found for: %s (point=%s)", query[:80], injection_point)
            return ""

        # Log retrieved chunks for debugging
        cat_names = [c.category.value for c in all_chunks]
        logger.info(
            "RAG: %d chunks for %s (categories: %s) query=%r",
            len(all_chunks), injection_point,
            ", ".join(sorted(set(cat_names))),
            query[:80],
        )
        for chunk in all_chunks:
            preview = chunk.text[:100].replace("\n", " ")
            logger.debug(
                "  RAG chunk: [%s] %s (rel=%.2f) %r...",
                chunk.category.value, chunk.section_title or chunk.source_file,
                chunk.relevance, preview,
            )

        return format_knowledge_context(all_chunks, max_tokens=max_tokens)

    def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[KnowledgeChunk]:
        """Search all providers for debugging/CLI. Returns raw chunks."""
        if not self._loaded:
            return []

        all_chunks: list[KnowledgeChunk] = []
        for provider in self._file_providers:
            chunks = provider.retrieve(query, max_chunks=max_results)
            all_chunks.extend(chunks)

        return sorted(all_chunks, key=lambda c: c.relevance, reverse=True)[:max_results]

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def total_chunks(self) -> int:
        return sum(fp.chunk_count for fp in self._file_providers)
