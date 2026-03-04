"""Base dialect ABC — contract all database dialects must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExplainResult:
    """Normalized output from any dialect's EXPLAIN."""

    estimated_rows: int | None = None
    estimated_cost: float | None = None
    scan_type: str = "unknown"
    join_types: list[str] = field(default_factory=list)
    uses_index: bool = False
    warnings: list[str] = field(default_factory=list)
    raw_plan: dict | str = ""


class DatabaseDialect(ABC):
    """Abstract base for database-specific behavior.

    Each dialect maps to one or more SQLAlchemy URL schemes.
    """

    # Subclasses set this to their accepted scheme names
    names: list[str] = []

    @abstractmethod
    def get_connect_args(
        self, connect_timeout: int = 10, query_timeout: int = 30
    ) -> dict[str, Any]:
        """Return dialect-specific connect_args for SQLAlchemy create_engine."""

    @abstractmethod
    def get_system_schemas(self) -> set[str]:
        """Return schema names to exclude from introspection."""

    def get_row_count_query(self, schema: str) -> str | None:
        """Return a query to get row counts for all tables in a schema.

        Should return columns: table_name, row_count.
        Return None if not supported (fallback to COUNT(*)).
        """
        return None

    def get_column_stats_query(self, schema: str, table: str) -> str | None:
        """Return a query to get column statistics (n_distinct, null_frac, avg_width).

        Return None if not supported.
        """
        return None

    def get_index_details_query(self, schema: str, table: str) -> str | None:
        """Return a query to get index details for a table.

        Return None to use SQLAlchemy's inspector.get_indexes().
        """
        return None

    @abstractmethod
    def add_limit(self, query: str, n: int) -> str:
        """Wrap a query to return at most n rows."""

    def add_random_limit(self, query: str, n: int) -> str:
        """Wrap a query to return n random rows. Default: ORDER BY RANDOM()."""
        return f"SELECT * FROM ({query}) _t ORDER BY RANDOM() LIMIT {n}"

    def add_sampling(
        self, query: str, table: str, row_count: int, sample_size: int
    ) -> str:
        """Rewrite query to sample from a large table. Default: TABLESAMPLE."""
        pct = max(0.1, min(100.0, (sample_size / max(row_count, 1)) * 100))
        return query.replace(table, f"{table} TABLESAMPLE SYSTEM({pct:.1f})")

    @abstractmethod
    def get_sql_syntax_rules(self) -> str:
        """Return dialect-specific SQL syntax rules for LLM prompts."""

    def quote_identifier(self, name: str) -> str:
        """Quote an identifier. Default uses double quotes."""
        return f'"{name}"'

    def get_retryable_errors(self) -> list[str]:
        """Return substrings that identify transient/retryable errors."""
        return ["connection reset", "connection refused", "timeout"]

    @abstractmethod
    def get_explain_prefix(self) -> str:
        """Return the EXPLAIN command prefix for this dialect."""

    def parse_explain_output(self, rows: list[dict]) -> ExplainResult:
        """Parse dialect-specific EXPLAIN output into ExplainResult.

        Default: store raw output, no parsing.
        """
        return ExplainResult(raw_plan=rows)

    def get_backend_pid_query(self) -> str | None:
        """Return a query to get the current connection's backend PID.

        Used for query cancellation. Return None if not supported.
        """
        return None

    def get_cancel_query(self, pid: int) -> str | None:
        """Return a query to cancel a running query by backend PID.

        Return None if not supported.
        """
        return None
