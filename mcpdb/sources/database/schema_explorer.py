"""Schema introspection — tables, columns, PKs, FKs, indexes, row counts."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from mcpdb.sources.base import ColumnInfo, TableInfo
from mcpdb.sources.database.connector import DatabaseConnector

logger = logging.getLogger("mcpdb.schema")


class TableSizeTag(Enum):
    SMALL = "SMALL"          # < 10K rows
    MEDIUM = "MEDIUM"        # 10K - 100K rows
    LARGE = "LARGE"          # 100K - 1M rows
    VERY_LARGE = "VERY_LARGE"  # > 1M rows


def classify_table_size(row_count: int | None) -> TableSizeTag:
    if row_count is None:
        return TableSizeTag.MEDIUM  # Conservative default
    if row_count < 10_000:
        return TableSizeTag.SMALL
    if row_count < 100_000:
        return TableSizeTag.MEDIUM
    if row_count < 1_000_000:
        return TableSizeTag.LARGE
    return TableSizeTag.VERY_LARGE


class SchemaExplorer:
    """Introspects database schema using SQLAlchemy inspector + dialect queries."""

    def __init__(self, connector: DatabaseConnector) -> None:
        self._connector = connector
        self._dialect = connector.dialect
        self._inspector = connector.inspector

    def explore(self, schema: str | None = None) -> list[TableInfo]:
        """Introspect all tables in the given schema (or default schema).

        Returns TableInfo objects with columns, PKs, FKs, indexes, row counts.
        """
        schemas = [schema] if schema else self._connector.get_schemas()
        all_tables: list[TableInfo] = []

        for s in schemas:
            try:
                table_names = self._inspector.get_table_names(schema=s)
            except Exception as e:
                logger.warning("Failed to list tables in schema %s: %s", s, e)
                continue

            # Try bulk row count query
            row_counts = self._get_row_counts(s, table_names)

            for table_name in table_names:
                try:
                    table_info = self._explore_table(s, table_name, row_counts)
                    all_tables.append(table_info)
                except Exception as e:
                    logger.warning("Failed to explore table %s.%s: %s", s, table_name, e)

        return all_tables

    def _explore_table(
        self,
        schema: str,
        table_name: str,
        row_counts: dict[str, int],
    ) -> TableInfo:
        """Explore a single table."""
        # Columns
        columns = []
        for col in self._inspector.get_columns(table_name, schema=schema):
            columns.append(ColumnInfo(
                name=col["name"],
                dtype=str(col["type"]),
                nullable=col.get("nullable", True),
            ))

        # Primary keys
        try:
            pk_constraint = self._inspector.get_pk_constraint(table_name, schema=schema)
            primary_keys = pk_constraint.get("constrained_columns", []) if pk_constraint else []
        except Exception:
            primary_keys = []

        # Indexes
        try:
            indexes = [
                {"name": idx["name"], "columns": idx["column_names"], "unique": idx.get("unique", False)}
                for idx in self._inspector.get_indexes(table_name, schema=schema)
            ]
        except Exception:
            indexes = []

        # Row count
        row_count = row_counts.get(table_name)

        return TableInfo(
            name=table_name,
            columns=columns,
            row_count=row_count,
            schema=schema,
            primary_keys=primary_keys,
            indexes=indexes,
        )

    def _get_row_counts(
        self, schema: str, table_names: list[str]
    ) -> dict[str, int]:
        """Get row counts for tables, using dialect query or COUNT(*)."""
        counts: dict[str, int] = {}

        # Try dialect-specific bulk query first
        query = self._dialect.get_row_count_query(schema)
        if query:
            try:
                rows = self._connector.execute_raw(query)
                for row in rows:
                    name = row.get("table_name")
                    count = row.get("row_count")
                    if name and count is not None:
                        counts[name] = int(count)
                return counts
            except Exception as e:
                logger.debug("Dialect row count query failed: %s", e)

        # Fallback: COUNT(*) per table
        for table_name in table_names:
            try:
                quoted = self._dialect.quote_identifier(table_name)
                schema_prefix = f"{self._dialect.quote_identifier(schema)}." if schema else ""
                result = self._connector.execute_raw(
                    f"SELECT COUNT(*) AS cnt FROM {schema_prefix}{quoted}"
                )
                if result:
                    counts[table_name] = int(result[0]["cnt"])
            except Exception as e:
                logger.debug("COUNT(*) failed for %s: %s", table_name, e)

        return counts

    def get_foreign_keys(self, schema: str | None = None) -> list[dict[str, Any]]:
        """Get all foreign key relationships in the schema."""
        schemas = [schema] if schema else self._connector.get_schemas()
        fks: list[dict[str, Any]] = []

        for s in schemas:
            try:
                table_names = self._inspector.get_table_names(schema=s)
            except Exception:
                continue

            for table_name in table_names:
                try:
                    for fk in self._inspector.get_foreign_keys(table_name, schema=s):
                        fks.append({
                            "source_table": table_name,
                            "source_schema": s,
                            "source_columns": fk["constrained_columns"],
                            "target_table": fk["referred_table"],
                            "target_schema": fk.get("referred_schema", s),
                            "target_columns": fk["referred_columns"],
                        })
                except Exception:
                    pass

        return fks
