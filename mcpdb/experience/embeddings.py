"""Embedding service — provider-agnostic text embeddings with Jaccard fallback."""

from __future__ import annotations

import math
import re
from typing import Any

# Common English stop words to ignore in Jaccard similarity
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
    "neither", "each", "every", "all", "any", "few", "more", "most",
    "other", "some", "such", "no", "only", "own", "same", "than",
    "too", "very", "just", "because", "as", "until", "while",
    "of", "at", "by", "for", "with", "about", "against", "between",
    "through", "during", "before", "after", "above", "below", "to",
    "from", "up", "down", "in", "out", "on", "off", "over", "under",
    "again", "further", "then", "once", "here", "there", "when",
    "where", "why", "how", "what", "which", "who", "whom", "this",
    "that", "these", "those", "i", "me", "my", "we", "our", "you",
    "your", "he", "him", "his", "she", "her", "it", "its", "they",
    "them", "their", "show", "get", "give", "tell", "find", "list",
})


def _tokenize(text: str) -> set[str]:
    """Tokenize text into meaningful word tokens."""
    words = re.findall(r"[a-z0-9_]+", text.lower())
    return {w for w in words if w not in _STOP_WORDS and len(w) > 1}


def jaccard_similarity(text_a: str, text_b: str) -> float:
    """Compute Jaccard similarity between two texts.

    Returns a value between 0.0 and 1.0.
    """
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)

    if not tokens_a or not tokens_b:
        return 0.0

    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b

    return len(intersection) / len(union)


def weighted_similarity(
    text_a: str,
    text_b: str,
    table_names_a: set[str] | None = None,
    table_names_b: set[str] | None = None,
    table_overlap_boost: float = 0.15,
) -> float:
    """Compute similarity with optional table-overlap boosting.

    If both questions reference the same tables, boost the score.
    """
    base = jaccard_similarity(text_a, text_b)

    if table_names_a and table_names_b:
        table_overlap = len(table_names_a & table_names_b) / max(
            len(table_names_a | table_names_b), 1
        )
        base = min(1.0, base + table_overlap * table_overlap_boost)

    return base


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
