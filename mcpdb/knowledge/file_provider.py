"""File-based knowledge provider — loads markdown/YAML/SQL from directories."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from mcpdb.knowledge.base import (
    EmbeddingProvider,
    KnowledgeCategory,
    KnowledgeChunk,
)
from mcpdb.knowledge.chunker import chunk_file
from mcpdb.knowledge.index import KnowledgeIndex

logger = logging.getLogger("mcpdb.knowledge.file_provider")

_INDEX_FILENAME = "_knowledge_index.pkl"
_SUPPORTED_EXTENSIONS = {".md", ".markdown", ".yml", ".yaml", ".sql"}


class FileKnowledgeProvider:
    """Loads knowledge from filesystem directories and provides retrieval.

    Scans directories for .md, .yml, .yaml, .sql files, chunks them,
    and builds a hybrid BM25 + optional embedding index.

    Index is cached to disk (_knowledge_index.pkl) and rebuilt when files change.
    """

    def __init__(
        self,
        directories: list[str | Path],
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._directories = [Path(d).expanduser().resolve() for d in directories]
        self._embedding_provider = embedding_provider
        self._index: KnowledgeIndex | None = None
        self._chunk_count: int = 0

    def load(self) -> int:
        """Scan directories, chunk files, build index. Returns chunk count."""
        t0 = time.monotonic()

        # Collect all files from all directories
        all_files: list[tuple[Path, Path]] = []  # (file_path, base_dir)
        for directory in self._directories:
            if not directory.exists():
                logger.debug("Knowledge directory does not exist, skipping: %s", directory)
                continue
            if not directory.is_dir():
                logger.debug("Knowledge path is not a directory, skipping: %s", directory)
                continue

            for ext in _SUPPORTED_EXTENSIONS:
                for fpath in directory.rglob(f"*{ext}"):
                    if fpath.name.startswith("_") or fpath.name.startswith("."):
                        continue
                    all_files.append((fpath, directory))

        if not all_files:
            logger.info("No knowledge files found in %d directories", len(self._directories))
            return 0

        # Check if cached index is still valid
        index_paths = [d / _INDEX_FILENAME for d in self._directories if d.exists()]
        cached_index = self._try_load_cached(index_paths, all_files)
        if cached_index is not None:
            self._index = cached_index
            self._chunk_count = len(cached_index)
            elapsed = time.monotonic() - t0
            logger.info(
                "Loaded cached knowledge index: %d chunks in %.1fs from %d files",
                self._chunk_count, elapsed, len(all_files),
            )
            return self._chunk_count

        # Build fresh index
        self._index = KnowledgeIndex(embedding_provider=self._embedding_provider)
        total_docs = 0
        for fpath, base_dir in all_files:
            docs = chunk_file(fpath, base_dir=base_dir)
            if docs:
                self._index.add_batch(docs)
                total_docs += len(docs)

        # Build embeddings if provider available
        if self._embedding_provider and self._embedding_provider.is_available():
            self._index.build_embeddings()

        self._chunk_count = len(self._index)

        # Cache the index
        if self._directories:
            cache_dir = self._directories[0]
            if cache_dir.exists():
                try:
                    self._index.save(cache_dir / _INDEX_FILENAME)
                except Exception as e:
                    logger.debug("Failed to cache index: %s", e)

        elapsed = time.monotonic() - t0
        embed_info = ""
        if self._embedding_provider and self._embedding_provider.is_available():
            embed_info = f", embedding={self._embedding_provider.__class__.__name__}"
        logger.info(
            "Built knowledge index: %d chunks from %d files in %.1fs (bm25%s)",
            self._chunk_count, len(all_files), elapsed, embed_info,
        )

        return self._chunk_count

    def retrieve(
        self,
        query: str,
        *,
        categories: set[KnowledgeCategory] | None = None,
        max_chunks: int = 10,
        table_names: list[str] | None = None,
    ) -> list[KnowledgeChunk]:
        """Retrieve relevant knowledge chunks for a query."""
        if self._index is None:
            return []

        return self._index.search(
            query,
            categories=categories,
            top_k=max_chunks,
            table_names=table_names,
        )

    @property
    def chunk_count(self) -> int:
        return self._chunk_count

    def _try_load_cached(
        self,
        index_paths: list[Path],
        all_files: list[tuple[Path, Path]],
    ) -> KnowledgeIndex | None:
        """Try to load a cached index if it's still valid."""
        for idx_path in index_paths:
            if not idx_path.exists():
                continue

            idx_mtime = idx_path.stat().st_mtime
            # Check if any source file is newer than the index
            any_newer = False
            for fpath, _ in all_files:
                if fpath.stat().st_mtime > idx_mtime:
                    any_newer = True
                    break

            if any_newer:
                logger.debug("Cached index is stale, will rebuild")
                continue

            try:
                return KnowledgeIndex.load(idx_path, self._embedding_provider)
            except Exception as e:
                logger.debug("Failed to load cached index: %s", e)

        return None
