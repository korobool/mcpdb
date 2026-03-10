"""Embedding providers — LLM API, local model, or no-op."""

from __future__ import annotations

import logging
from typing import Any

from mcpdb.knowledge.base import EmbeddingProvider

logger = logging.getLogger("mcpdb.knowledge.embeddings")


class NoEmbeddingProvider(EmbeddingProvider):
    """Stub provider — BM25-only mode, no vectors."""

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return []

    @property
    def dimension(self) -> int:
        return 0

    def is_available(self) -> bool:
        return False


class LLMEmbeddingProvider(EmbeddingProvider):
    """Uses the configured LLM provider's embedding API (Gemini, OpenAI).

    Zero new dependencies — reuses the existing LLM provider.
    """

    def __init__(self, llm_provider: Any) -> None:
        self._llm = llm_provider
        self._dimension: int = 0
        self._cache: dict[str, list[float]] = {}

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts via the LLM embedding API."""
        try:
            results = []
            for text in texts:
                vec = self._embed_single(text)
                results.append(vec)
            if results and results[0]:
                self._dimension = len(results[0])
            return results
        except Exception as e:
            logger.warning("LLM embedding failed: %s — falling back to no embeddings", e)
            return [[] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query, with caching."""
        if text in self._cache:
            return self._cache[text]
        try:
            vec = self._embed_single(text)
            if vec:
                self._cache[text] = vec
            return vec
        except Exception as e:
            logger.debug("Query embedding failed: %s", e)
            return []

    def _embed_single(self, text: str) -> list[float]:
        """Call the LLM provider's embedding endpoint."""
        # Try Gemini-style embedding
        if hasattr(self._llm, "embed"):
            return self._llm.embed(text)

        # Try the provider's raw client
        if hasattr(self._llm, "_client"):
            client = self._llm._client
            # google-genai SDK
            if hasattr(client, "models") and hasattr(client.models, "embed_content"):
                response = client.models.embed_content(
                    model="text-embedding-004",
                    contents=text,
                )
                return list(response.embeddings[0].values)

        logger.debug("LLM provider does not support embeddings")
        return []

    @property
    def dimension(self) -> int:
        return self._dimension

    def is_available(self) -> bool:
        return self._dimension > 0


class LocalEmbeddingProvider(EmbeddingProvider):
    """Uses sentence-transformers for local embedding.

    Optional dependency: pip install mcpdb[embeddings]
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model: Any = None
        self._dimension: int = 384  # default for MiniLM

    def _load_model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self._model_name)
                self._dimension = self._model.get_sentence_embedding_dimension()
                logger.info("Loaded local embedding model: %s (%d dims)",
                            self._model_name, self._dimension)
            except ImportError:
                raise ImportError(
                    "Local embeddings require sentence-transformers. "
                    "Install with: pip install mcpdb[embeddings]"
                )
        return self._model

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        model = self._load_model()
        vecs = model.encode(texts, show_progress_bar=False)
        return [v.tolist() for v in vecs]

    def embed_query(self, text: str) -> list[float]:
        model = self._load_model()
        vec = model.encode(text, show_progress_bar=False)
        return vec.tolist()

    @property
    def dimension(self) -> int:
        return self._dimension


def resolve_embedding_provider(
    mode: str,
    llm_provider: Any = None,
) -> EmbeddingProvider:
    """Resolve the embedding provider based on config mode.

    Modes:
        auto  — try local → try llm → fall back to none
        local — use sentence-transformers (error if not installed)
        llm   — use LLM provider's embedding API
        none  — BM25-only, no vectors
    """
    if mode == "none":
        return NoEmbeddingProvider()

    if mode == "local":
        return LocalEmbeddingProvider()

    if mode == "llm":
        if llm_provider is not None:
            return LLMEmbeddingProvider(llm_provider)
        logger.info("No LLM provider for embeddings, falling back to none")
        return NoEmbeddingProvider()

    # auto mode
    try:
        provider = LocalEmbeddingProvider()
        provider._load_model()
        logger.info("Auto-resolved embedding: local (%s)", provider._model_name)
        return provider
    except (ImportError, Exception):
        pass

    if llm_provider is not None:
        provider = LLMEmbeddingProvider(llm_provider)
        logger.info("Auto-resolved embedding: llm")
        return provider

    logger.info("Auto-resolved embedding: none (BM25-only)")
    return NoEmbeddingProvider()
