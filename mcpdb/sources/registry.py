"""Source registry — manages active data sources within a session."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from mcpdb.sources.base import (
    DataSource,
    QueryableSource,
    SourceMetadata,
    SpreadsheetSource,
)

if TYPE_CHECKING:
    pass


class SourceNotFoundError(KeyError):
    """Raised when a source_id is not in the registry."""


class SourceRegistry:
    """Thread-safe registry of active data sources."""

    def __init__(self) -> None:
        self._sources: dict[str, DataSource] = {}
        self._lock = threading.Lock()

    def add_source(self, source: DataSource) -> str:
        """Add a source and return its source_id."""
        metadata = source.get_metadata()
        source_id = metadata.source_id
        with self._lock:
            if source_id in self._sources:
                raise ValueError(f"Source '{source_id}' already exists")
            self._sources[source_id] = source
        return source_id

    def remove_source(self, source_id: str) -> None:
        """Remove and close a source."""
        with self._lock:
            source = self._sources.pop(source_id, None)
        if source is None:
            raise SourceNotFoundError(f"Source '{source_id}' not found")
        source.close()

    def get_source(self, source_id: str) -> DataSource:
        """Look up a source by ID."""
        with self._lock:
            source = self._sources.get(source_id)
        if source is None:
            raise SourceNotFoundError(f"Source '{source_id}' not found")
        return source

    def list_sources(self) -> list[SourceMetadata]:
        """Return metadata for all active sources."""
        with self._lock:
            sources = list(self._sources.values())
        return [s.get_metadata() for s in sources]

    def get_combined_context(self) -> str:
        """Build combined LLM context from all active sources."""
        with self._lock:
            sources = list(self._sources.values())
        if not sources:
            return "No data sources connected."
        parts = []
        for i, source in enumerate(sources, 1):
            parts.append(f"### Source {i}: {source.get_metadata().display_name}")
            parts.append(source.get_context_description())
            parts.append("")
        return "\n".join(parts)

    def get_queryable_sources(self) -> list[QueryableSource]:
        """Return all sources that support SQL querying."""
        with self._lock:
            return [s for s in self._sources.values() if isinstance(s, QueryableSource)]

    def get_spreadsheet_sources(self) -> list[SpreadsheetSource]:
        """Return all sources that are spreadsheets."""
        with self._lock:
            return [s for s in self._sources.values() if isinstance(s, SpreadsheetSource)]

    def close_all(self) -> None:
        """Close and remove all sources."""
        with self._lock:
            sources = list(self._sources.values())
            self._sources.clear()
        for source in sources:
            source.close()

    def __len__(self) -> int:
        with self._lock:
            return len(self._sources)

    def __contains__(self, source_id: str) -> bool:
        with self._lock:
            return source_id in self._sources
