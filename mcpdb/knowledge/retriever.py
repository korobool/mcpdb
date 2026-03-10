"""Knowledge retriever — token-budgeted formatting for prompt injection."""

from __future__ import annotations

import logging

from mcpdb.knowledge.base import KnowledgeChunk

logger = logging.getLogger("mcpdb.knowledge.retriever")


def estimate_tokens(text: str) -> int:
    """Rough token estimate: word_count * 1.3."""
    return int(len(text.split()) * 1.3)


def format_knowledge_context(
    chunks: list[KnowledgeChunk],
    *,
    max_tokens: int = 2000,
) -> str:
    """Format retrieved chunks into a string for prompt injection.

    Sorts by relevance, deduplicates, and enforces token budget.
    Returns empty string if no chunks or budget is exhausted.
    """
    if not chunks:
        return ""

    # Sort by relevance (descending)
    sorted_chunks = sorted(chunks, key=lambda c: c.relevance, reverse=True)

    # Deduplicate by section title
    seen_titles: set[str] = set()
    unique: list[KnowledgeChunk] = []
    for chunk in sorted_chunks:
        key = chunk.section_title.lower().strip()
        if key and key in seen_titles:
            continue
        seen_titles.add(key)
        unique.append(chunk)

    # Build within token budget
    parts: list[str] = []
    budget_used = 0
    selected_count = 0

    for chunk in unique:
        chunk_tokens = chunk.token_estimate or estimate_tokens(chunk.text)
        if budget_used + chunk_tokens > max_tokens and parts:
            # Try smaller chunks before giving up
            continue
        parts.append(f"### {chunk.section_title}\n{chunk.text}")
        budget_used += chunk_tokens
        selected_count += 1

        if budget_used >= max_tokens:
            break

    result = "\n\n---\n\n".join(parts)

    if selected_count > 0:
        logger.info(
            "Knowledge context: %d chunks (%d tokens) from %d candidates",
            selected_count, budget_used, len(chunks),
        )
        for chunk in unique[:selected_count]:
            logger.debug(
                "  → [%s] \"%s\" (score: %.2f, %d tok)",
                chunk.category.value,
                chunk.section_title[:60],
                chunk.relevance,
                chunk.token_estimate,
            )

    return result
