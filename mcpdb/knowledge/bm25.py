"""BM25 ranking index — pure Python, zero dependencies."""

from __future__ import annotations

import math
import re
from collections import Counter

# Stop words — superset of experience/embeddings.py list
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
    "please", "want", "like", "know", "think", "see", "look",
})

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> list[str]:
    """Tokenize text into meaningful word tokens for BM25."""
    words = _TOKEN_RE.findall(text.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 1]


class BM25Index:
    """Okapi BM25 ranking index.

    Standard BM25 with k1=1.5, b=0.75 (classic defaults).
    Pure Python, no external dependencies. Fast enough for <10K documents.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._tf: list[Counter] = []          # per-doc term frequencies
        self._df: Counter = Counter()          # document frequencies
        self._doc_lengths: list[int] = []      # token count per doc
        self._avg_dl: float = 0.0
        self._n_docs: int = 0

    def add(self, text: str) -> int:
        """Add a document and return its doc_id (0-based index)."""
        tokens = tokenize(text)
        tf = Counter(tokens)
        doc_id = self._n_docs

        self._tf.append(tf)
        self._doc_lengths.append(len(tokens))

        for term in tf:
            self._df[term] += 1

        self._n_docs += 1
        total_len = sum(self._doc_lengths)
        self._avg_dl = total_len / self._n_docs if self._n_docs else 0.0

        return doc_id

    def add_batch(self, texts: list[str]) -> int:
        """Add multiple documents. Returns count added."""
        for text in texts:
            self.add(text)
        return len(texts)

    def search(
        self,
        query: str,
        candidates: list[int] | None = None,
        top_k: int = 10,
    ) -> list[tuple[int, float]]:
        """Score query against documents.

        Args:
            query: Search query text.
            candidates: Optional list of doc_ids to score (for pre-filtering).
                        If None, scores all documents.
            top_k: Maximum number of results to return.

        Returns:
            List of (doc_id, score) tuples sorted by descending score.
        """
        if self._n_docs == 0:
            return []

        query_terms = tokenize(query)
        if not query_terms:
            return []

        doc_ids = candidates if candidates is not None else range(self._n_docs)
        n = self._n_docs
        avg_dl = self._avg_dl
        k1 = self.k1
        b = self.b

        # Pre-compute IDF for query terms
        idf_cache: dict[str, float] = {}
        for term in query_terms:
            df = self._df.get(term, 0)
            if df > 0:
                idf_cache[term] = math.log((n - df + 0.5) / (df + 0.5) + 1.0)

        if not idf_cache:
            return []

        scores: list[tuple[int, float]] = []
        for doc_id in doc_ids:
            s = 0.0
            tf = self._tf[doc_id]
            dl = self._doc_lengths[doc_id]
            for term, idf in idf_cache.items():
                freq = tf.get(term, 0)
                if freq == 0:
                    continue
                num = freq * (k1 + 1)
                den = freq + k1 * (1 - b + b * dl / avg_dl)
                s += idf * num / den
            if s > 0:
                scores.append((doc_id, s))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def __len__(self) -> int:
        return self._n_docs
