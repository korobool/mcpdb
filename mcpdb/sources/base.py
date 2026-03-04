"""Base data source abstractions."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd


class SourceType(Enum):
    DATABASE = "database"
    CSV = "csv"
    EXCEL = "excel"


@dataclass
class ColumnInfo:
    name: str
    dtype: str
    nullable: bool = True
    description: str = ""


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo]
    row_count: int | None = None
    schema: str | None = None
    source_file: str | None = None
    sheet_name: str | None = None
    primary_keys: list[str] = field(default_factory=list)
    indexes: list[dict] = field(default_factory=list)


@dataclass
class SourceMetadata:
    """Unified metadata that every source must provide."""

    source_id: str
    source_type: SourceType
    display_name: str
    tables: list[TableInfo]
    capabilities: set[str]
    raw_info: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source_type"] = self.source_type.value
        d["capabilities"] = sorted(self.capabilities)
        return d


class DataSource(ABC):
    """Base interface for all data sources."""

    @abstractmethod
    def get_metadata(self) -> SourceMetadata:
        """Return schema/structure metadata for the LLM context."""

    @abstractmethod
    def get_context_description(self) -> str:
        """Return a text description suitable for injection into LLM prompts."""

    def get_schema_json(self) -> str:
        """Return schema as JSON (for MCP resources)."""
        return json.dumps(self.get_metadata().to_dict(), indent=2)

    def get_tables(self) -> list[TableInfo]:
        """Return table/sheet list."""
        return self.get_metadata().tables

    def get_relationships(self) -> list[dict]:
        """Return FK/inferred relationships."""
        return []

    @abstractmethod
    def close(self) -> None:
        """Release resources. Must be idempotent."""

    @property
    @abstractmethod
    def source_type(self) -> SourceType:
        """Return the type of this source."""


class QueryableSource(DataSource):
    """Source that supports SQL-like querying (databases, CSV via DuckDB)."""

    @abstractmethod
    def execute_query(self, query: str, max_rows: int = 100) -> pd.DataFrame:
        """Execute a SQL query and return results."""

    @abstractmethod
    def get_sample(self, table_name: str, limit: int = 5) -> pd.DataFrame:
        """Return sample rows from a table/dataset."""


class SpreadsheetSource(DataSource):
    """Source that represents a workbook with sheets and cells (Excel)."""

    @abstractmethod
    def list_sheets(self) -> list[dict]:
        """List all sheets with metadata."""

    @abstractmethod
    def read_range(
        self,
        sheet: str,
        range_str: str | None = None,
        include_formulas: bool = False,
    ) -> Any:
        """Read a range of cells with optional formula extraction."""

    @abstractmethod
    def get_sheet_structure(self, sheet: str) -> Any:
        """Analyze sheet layout: detect tables, headers, merged regions."""

    @abstractmethod
    def extract_table(self, sheet: str, table_range: str) -> pd.DataFrame:
        """Extract a rectangular region as a DataFrame."""
