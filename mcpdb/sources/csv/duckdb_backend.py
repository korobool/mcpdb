"""DuckDB backend — in-memory SQL engine for CSV and cross-source queries."""

from __future__ import annotations

import logging
from typing import Any

import duckdb
import pandas as pd

logger = logging.getLogger("mcpdb.csv.duckdb")


class DuckDBBackend:
    """Manages a DuckDB in-memory session for SQL querying.

    Loads CSV files directly via DuckDB's read_csv_auto (no pandas intermediary),
    keeping memory usage low and enabling out-of-core processing for large files.
    """

    def __init__(self, memory_limit: str = "2GB", threads: int = 4) -> None:
        self._conn = duckdb.connect(":memory:")
        self._conn.execute(f"SET memory_limit = '{memory_limit}'")
        self._conn.execute(f"SET threads = {threads}")
        self._tables: dict[str, int] = {}  # table_name → row_count
        logger.info("DuckDB backend created (memory_limit=%s)", memory_limit)

    def load_csv(
        self,
        name: str,
        file_path: str,
        delimiter: str = ",",
        has_header: bool = True,
    ) -> tuple[int, int, list[str]]:
        """Load a CSV file directly into DuckDB as a table.

        Returns (row_count, column_count, column_names).
        """
        safe_name = _sanitize_name(name)
        header_flag = "true" if has_header else "false"
        # Escape single quotes in path
        escaped_path = file_path.replace("'", "''")
        self._conn.execute(
            f"CREATE OR REPLACE TABLE {safe_name} AS "
            f"SELECT * FROM read_csv_auto('{escaped_path}', "
            f"delim='{delimiter}', header={header_flag}, ignore_errors=true)"
        )

        # Get row count and column info
        row_count = self._conn.execute(f"SELECT COUNT(*) FROM {safe_name}").fetchone()[0]
        cols_result = self._conn.execute(f"DESCRIBE {safe_name}").fetchall()
        col_names = [row[0] for row in cols_result]

        # Rename columns if no header (DuckDB auto-generates column0, column1, ...)
        if not has_header:
            for i, old_name in enumerate(col_names):
                new_name = f"col_{i}"
                self._conn.execute(f"ALTER TABLE {safe_name} RENAME COLUMN \"{old_name}\" TO {new_name}")
            col_names = [f"col_{i}" for i in range(len(col_names))]

        self._tables[safe_name] = row_count
        logger.info("Loaded CSV '%s' → table '%s' (%d rows, %d columns)",
                     file_path, safe_name, row_count, len(col_names))
        return row_count, len(col_names), col_names

    def register_dataframe(
        self,
        name: str,
        df: pd.DataFrame,
    ) -> None:
        """Register a DataFrame as a queryable table in DuckDB."""
        safe_name = _sanitize_name(name)
        self._conn.register(safe_name, df)
        self._tables[safe_name] = len(df)
        logger.info("Registered table '%s' (%d rows, %d columns)",
                     safe_name, len(df), len(df.columns))

    def unregister_table(self, name: str) -> None:
        """Remove a table from the DuckDB session."""
        safe_name = _sanitize_name(name)
        try:
            self._conn.execute(f"DROP TABLE IF EXISTS {safe_name}")
        except Exception:
            pass
        self._tables.pop(safe_name, None)

    def execute_query(self, query: str, max_rows: int = 100) -> pd.DataFrame:
        """Execute a SQL query and return results as a DataFrame."""
        result = self._conn.execute(query)
        df = result.fetchdf()

        truncated = len(df) > max_rows
        if truncated:
            df = df.head(max_rows)

        df.attrs["mcpdb_truncated"] = truncated
        df.attrs["mcpdb_total_rows"] = len(df)
        return df

    def get_table_names(self) -> list[str]:
        """Return all registered table names."""
        return list(self._tables.keys())

    def get_table_info(self, table_name: str) -> list[dict[str, Any]]:
        """Get column info for a registered table."""
        safe_name = _sanitize_name(table_name)
        try:
            result = self._conn.execute(f"DESCRIBE {safe_name}")
            rows = result.fetchall()
            columns = result.description
            return [
                {
                    "name": row[0],
                    "type": row[1],
                    "null": row[2] if len(row) > 2 else "YES",
                }
                for row in rows
            ]
        except Exception as e:
            logger.warning("Failed to describe table %s: %s", safe_name, e)
            return []

    def get_row_count(self, table_name: str) -> int | None:
        """Get row count for a table (from cache)."""
        return self._tables.get(_sanitize_name(table_name))

    @property
    def table_count(self) -> int:
        return len(self._tables)

    def close(self) -> None:
        """Close the DuckDB connection."""
        try:
            self._conn.close()
        except Exception:
            pass
        logger.info("DuckDB backend closed")


def _sanitize_name(name: str) -> str:
    """Sanitize a table name for DuckDB (alphanumeric + underscore only)."""
    import re
    # Replace non-alphanumeric characters with underscores
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    # Ensure it starts with a letter or underscore
    if sanitized and sanitized[0].isdigit():
        sanitized = f"t_{sanitized}"
    return sanitized or "unnamed_table"
