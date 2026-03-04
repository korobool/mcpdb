"""Cross-source federation — query across multiple data sources."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from mcpdb.sources.base import QueryableSource, SourceType
from mcpdb.sources.csv.duckdb_backend import DuckDBBackend
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.federation")


@dataclass
class FederationPlan:
    """Plan for executing a cross-source query."""

    strategy: str  # "duckdb_attach", "pushdown_transfer", "full_transfer"
    source_queries: dict[str, str]  # source_id → subquery to execute
    final_query: str  # SQL to run in DuckDB after transfers
    transferred_tables: dict[str, str]  # duckdb_table_name → source_id


class CrossSourceEngine:
    """Executes queries that span multiple data sources.

    Strategy selection:
    1. If all sources are CSV (DuckDB-backed), query directly.
    2. If a source is SQLite, attach directly in DuckDB.
    3. Otherwise: execute subqueries on each source, transfer results to DuckDB,
       then run the final join/aggregation.
    """

    def __init__(self, memory_limit: str = "2GB") -> None:
        self._backend = DuckDBBackend(memory_limit=memory_limit)

    def execute_cross_source(
        self,
        sql: str,
        source_ids: list[str],
        registry: SourceRegistry,
        max_rows: int = 100,
    ) -> pd.DataFrame:
        """Execute a SQL query spanning multiple sources.

        Tables are referenced by their names as they appear in each source.
        For disambiguation, use {source_id}.{table_name} syntax or just
        the table name if unique across sources.
        """
        # Collect all queryable sources
        sources: dict[str, QueryableSource] = {}
        for sid in source_ids:
            source = registry.get_source(sid)
            if not isinstance(source, QueryableSource):
                raise ValueError(f"Source '{sid}' does not support SQL queries")
            sources[sid] = source

        # Build a unified DuckDB session with all tables
        table_registry: dict[str, str] = {}  # table_name → source_id

        for sid, source in sources.items():
            source_type = source.source_type

            if source_type == SourceType.CSV:
                # CSV sources are already DuckDB-backed — transfer their DataFrames
                self._transfer_csv_tables(sid, source)
                for t in source.get_tables():
                    table_registry[t.name] = sid

            elif source_type == SourceType.DATABASE:
                # Try SQLite direct attach, otherwise transfer
                conn_str = getattr(source, '_connection_string', '')
                if 'sqlite' in conn_str:
                    self._attach_sqlite(sid, source)
                    for t in source.get_tables():
                        table_registry[t.name] = sid
                else:
                    # Pushdown + transfer: get all tables as DataFrames
                    self._transfer_db_tables(sid, source)
                    for t in source.get_tables():
                        table_registry[t.name] = sid

        # Execute the query
        try:
            result = self._backend.execute_query(sql, max_rows=max_rows)
            return result
        finally:
            pass  # Backend cleanup handled by close()

    def _transfer_csv_tables(self, source_id: str, source: QueryableSource) -> None:
        """Transfer CSV source tables into the federation DuckDB."""
        for table in source.get_tables():
            try:
                df = source.execute_query(
                    f'SELECT * FROM "{table.name}"',
                    max_rows=1_000_000,
                )
                self._backend.register_dataframe(table.name, df)
                logger.debug("Transferred CSV table '%s' (%d rows)", table.name, len(df))
            except Exception as e:
                logger.warning("Failed to transfer CSV table %s: %s", table.name, e)

    def _attach_sqlite(self, source_id: str, source: QueryableSource) -> None:
        """Attach a SQLite database directly in DuckDB."""
        conn_str = getattr(source, '_connection_string', '')
        # Extract file path from sqlite:///path
        if ':///' in conn_str:
            db_path = conn_str.split(':///', 1)[1]
        elif '://' in conn_str:
            db_path = conn_str.split('://', 1)[1]
        else:
            db_path = conn_str

        try:
            self._backend._conn.execute("INSTALL sqlite; LOAD sqlite;")
        except Exception:
            pass  # Already installed

        alias = f"db_{source_id.replace('-', '_')[:20]}"
        try:
            self._backend._conn.execute(
                f"ATTACH '{db_path}' AS {alias} (TYPE sqlite, READ_ONLY)"
            )
            # Register table views
            for table in source.get_tables():
                try:
                    self._backend._conn.execute(
                        f'CREATE OR REPLACE VIEW "{table.name}" AS '
                        f'SELECT * FROM {alias}."{table.name}"'
                    )
                    self._backend._tables[table.name] = table.row_count or 0
                except Exception as e:
                    logger.warning("Failed to create view for %s: %s", table.name, e)
            logger.info("Attached SQLite database as '%s'", alias)
        except Exception as e:
            logger.warning("SQLite attach failed, falling back to transfer: %s", e)
            self._transfer_db_tables(source_id, source)

    def _transfer_db_tables(self, source_id: str, source: QueryableSource) -> None:
        """Transfer database tables into DuckDB via DataFrames."""
        for table in source.get_tables():
            try:
                # Sample up to 1M rows for safety
                dialect = getattr(source, 'dialect', None)
                if dialect:
                    quoted = dialect.quote_identifier(table.name)
                    query = dialect.add_limit(f"SELECT * FROM {quoted}", 1_000_000)
                else:
                    query = f'SELECT * FROM "{table.name}" LIMIT 1000000'

                df = source.execute_query(query, max_rows=1_000_000)
                self._backend.register_dataframe(table.name, df)
                logger.debug("Transferred DB table '%s' (%d rows)", table.name, len(df))
            except Exception as e:
                logger.warning("Failed to transfer table %s: %s", table.name, e)

    def close(self) -> None:
        """Clean up the federation DuckDB backend."""
        self._backend.close()


def execute_cross_source_query(
    sql: str,
    source_ids: list[str],
    registry: SourceRegistry,
    max_rows: int = 100,
) -> pd.DataFrame:
    """Convenience function: execute a cross-source query and return results."""
    engine = CrossSourceEngine()
    try:
        return engine.execute_cross_source(sql, source_ids, registry, max_rows)
    finally:
        engine.close()
