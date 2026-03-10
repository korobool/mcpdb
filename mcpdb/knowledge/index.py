"""Hybrid knowledge index — BM25 + optional vector embeddings."""

from __future__ import annotations

import logging
import math
import pickle
import time
from pathlib import Path
from typing import Any

from mcpdb.knowledge.base import (
    EmbeddingProvider,
    KnowledgeCategory,
    KnowledgeChunk,
    KnowledgeDocument,
)
from mcpdb.knowledge.bm25 import BM25Index

logger = logging.getLogger("mcpdb.knowledge.index")


class KnowledgeIndex:
    """Hybrid index combining BM25 with optional vector similarity.

    Retrieval flow:
    1. Category filter → narrow to relevant chunks
    2. BM25 score → rank by keyword relevance
    3. (Optional) Vector re-rank → reorder top results by semantic similarity
    4. Token budget → select top chunks within budget
    """

    def __init__(self, embedding_provider: EmbeddingProvider | None = None) -> None:
        self._documents: list[KnowledgeDocument] = []
        self._bm25 = BM25Index()
        self._embedding_provider = embedding_provider
        self._vectors: list[list[float]] = []  # parallel to _documents
        self._category_index: dict[KnowledgeCategory, list[int]] = {}

    def add(self, doc: KnowledgeDocument) -> int:
        """Add a document to the index. Returns its doc_id."""
        doc_id = len(self._documents)
        self._documents.append(doc)
        self._bm25.add(doc.content)

        # Category index
        cat_list = self._category_index.setdefault(doc.category, [])
        cat_list.append(doc_id)

        return doc_id

    def add_batch(self, docs: list[KnowledgeDocument]) -> int:
        """Add multiple documents. Returns count added."""
        for doc in docs:
            self.add(doc)
        return len(docs)

    def build_embeddings(self) -> int:
        """Compute and store embedding vectors for all documents.

        Call this after all documents are added. Returns count of vectors built.
        """
        if not self._embedding_provider or not self._embedding_provider.is_available():
            logger.debug("No embedding provider — skipping vector build")
            return 0

        if not self._documents:
            return 0

        logger.info("Building embeddings for %d chunks...", len(self._documents))
        t0 = time.monotonic()

        # Batch embed all document texts
        texts = [doc.content[:2000] for doc in self._documents]  # truncate for embedding
        try:
            self._vectors = self._embedding_provider.embed_batch(texts)
            elapsed = time.monotonic() - t0
            count = sum(1 for v in self._vectors if v)
            logger.info("Built %d embeddings in %.1fs", count, elapsed)
            return count
        except Exception as e:
            logger.warning("Embedding build failed: %s", e)
            self._vectors = []
            return 0

    def search(
        self,
        query: str,
        *,
        categories: set[KnowledgeCategory] | None = None,
        top_k: int = 10,
        table_names: list[str] | None = None,
    ) -> list[KnowledgeChunk]:
        """Search the index with category filtering, BM25, and optional re-ranking.

        Args:
            query: Natural language search query.
            categories: If set, only return chunks from these categories.
            top_k: Maximum number of results.
            table_names: Optional table names for boosting.

        Returns:
            List of KnowledgeChunk sorted by relevance (descending).
        """
        if not self._documents:
            return []

        # Stage 1: Category filter
        if categories:
            candidates = []
            for cat in categories:
                candidates.extend(self._category_index.get(cat, []))
            candidates = sorted(set(candidates))
            if not candidates:
                return []
        else:
            candidates = None

        # Stage 2: BM25 score
        bm25_results = self._bm25.search(query, candidates=candidates, top_k=top_k * 3)

        if not bm25_results:
            return []

        # Stage 2b: Table name boost
        if table_names:
            table_set = {t.lower() for t in table_names}
            boosted = []
            for doc_id, score in bm25_results:
                text_lower = self._documents[doc_id].content[:1000].lower()
                if any(t in text_lower for t in table_set):
                    boosted.append((doc_id, score * 1.5))
                else:
                    boosted.append((doc_id, score))
            bm25_results = sorted(boosted, key=lambda x: x[1], reverse=True)

        # Stage 3: Optional vector re-ranking
        if self._has_vectors():
            bm25_results = self._rerank_with_vectors(query, bm25_results[:top_k * 2])

        # Convert to KnowledgeChunks
        max_score = bm25_results[0][1] if bm25_results else 1.0
        chunks: list[KnowledgeChunk] = []
        for doc_id, score in bm25_results[:top_k]:
            doc = self._documents[doc_id]
            relevance = min(1.0, score / max_score) if max_score > 0 else 0.0
            chunks.append(KnowledgeChunk(
                id=f"{doc.source_label}::{doc.section_title}",
                text=doc.content,
                category=doc.category,
                relevance=relevance,
                tags=doc.tags,
                source_file=doc.source_label,
                section_title=doc.section_title,
            ))

        return chunks

    def _has_vectors(self) -> bool:
        """Check if we have usable vectors."""
        return (
            bool(self._vectors)
            and self._embedding_provider is not None
            and self._embedding_provider.is_available()
        )

    def _rerank_with_vectors(
        self,
        query: str,
        bm25_results: list[tuple[int, float]],
    ) -> list[tuple[int, float]]:
        """Re-rank BM25 results using vector cosine similarity."""
        assert self._embedding_provider is not None

        query_vec = self._embedding_provider.embed_query(query)
        if not query_vec:
            return bm25_results

        # Normalize BM25 scores to 0-1
        max_bm25 = max(s for _, s in bm25_results) if bm25_results else 1.0

        reranked: list[tuple[int, float]] = []
        for doc_id, bm25_score in bm25_results:
            if doc_id < len(self._vectors) and self._vectors[doc_id]:
                cos_sim = _cosine_similarity(query_vec, self._vectors[doc_id])
                bm25_norm = bm25_score / max_bm25 if max_bm25 > 0 else 0.0
                combined = 0.4 * bm25_norm + 0.6 * max(0.0, cos_sim)
                reranked.append((doc_id, combined))
            else:
                reranked.append((doc_id, bm25_score / max_bm25 if max_bm25 > 0 else 0.0))

        reranked.sort(key=lambda x: x[1], reverse=True)
        return reranked

    def save(self, path: Path) -> None:
        """Save index to disk (pickle)."""
        data = {
            "documents": self._documents,
            "vectors": self._vectors,
            "version": 1,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info("Saved index: %d chunks, %d vectors → %s",
                     len(self._documents), len(self._vectors), path)

    @classmethod
    def load(
        cls,
        path: Path,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> KnowledgeIndex:
        """Load index from disk. Rebuilds BM25 from stored documents."""
        with open(path, "rb") as f:
            data = pickle.load(f)

        idx = cls(embedding_provider=embedding_provider)
        docs = data.get("documents", [])
        for doc in docs:
            idx.add(doc)
        idx._vectors = data.get("vectors", [])

        logger.info("Loaded index: %d chunks, %d vectors from %s",
                     len(idx._documents), len(idx._vectors), path)
        return idx

    def __len__(self) -> int:
        return len(self._documents)

    def clear(self) -> None:
        """Clear all indexed data."""
        self._documents.clear()
        self._bm25 = BM25Index()
        self._vectors.clear()
        self._category_index.clear()


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
