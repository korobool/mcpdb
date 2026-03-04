"""DatabaseSource — full QueryableSource wrapping connector + schema + dialect."""

from __future__ import annotations

import hashlib
import logging
from typing import Any
from urllib.parse import urlparse

import pandas as pd

from mcpdb.sources.base import QueryableSource, SourceMetadata, SourceType, TableInfo
from mcpdb.sources.database.connector import DatabaseConnector
from mcpdb.sources.database.schema_explorer import SchemaExplorer, TableSizeTag, classify_table_size

logger = logging.getLogger("mcpdb.database")


def _make_source_id(connection_string: str) -> str:
    """Generate a stable, short source ID from a connection string."""
    parsed = urlparse(connection_string)
    # Use host + db name for a human-readable prefix
    host = parsed.hostname or "local"
    db = parsed.path.lstrip("/").split("/")[0] if parsed.path else "db"
    # Short hash for uniqueness
    h = hashlib.md5(connection_string.encode()).hexdigest()[:6]
    return f"db_{host}_{db}_{h}".replace(".", "_").replace("-", "_")


def _redact_connection_string(connection_string: str) -> str:
    """Remove password from connection string for display."""
    parsed = urlparse(connection_string)
    if parsed.password:
        return connection_string.replace(f":{parsed.password}@", ":***@")
    return connection_string


class DatabaseSource(QueryableSource):
    """Full database source implementation.

    Connects via SQLAlchemy, introspects schema, and provides SQL query execution.
    """

    def __init__(
        self,
        connection_string: str,
        display_name: str | None = None,
        connect_timeout: int = 10,
        query_timeout: int = 30,
    ) -> None:
        self._connection_string = connection_string
        self._source_id = _make_source_id(connection_string)
        self._display_name = display_name or _redact_connection_string(connection_string)
        self._closed = False

        # Connect
        self._connector = DatabaseConnector(
            connection_string,
            connect_timeout=connect_timeout,
            query_timeout=query_timeout,
        )

        # Introspect schema
        self._schema_explorer = SchemaExplorer(self._connector)
        self._tables: list[TableInfo] = self._schema_explorer.explore()
        self._foreign_keys = self._schema_explorer.get_foreign_keys()

        # Classify table sizes
        self._size_tags: dict[str, TableSizeTag] = {
            t.name: classify_table_size(t.row_count) for t in self._tables
        }

        logger.info(
            "Connected to %s: %d tables found",
            self._display_name,
            len(self._tables),
        )

    @property
    def source_type(self) -> SourceType:
        return SourceType.DATABASE

    @property
    def dialect(self):
        return self._connector.dialect

    @property
    def connector(self) -> DatabaseConnector:
        return self._connector

    def get_metadata(self) -> SourceMetadata:
        return SourceMetadata(
            source_id=self._source_id,
            source_type=SourceType.DATABASE,
            display_name=self._display_name,
            tables=self._tables,
            capabilities={"sql", "python"},
            raw_info={
                "size_tags": {k: v.value for k, v in self._size_tags.items()},
                "foreign_keys": self._foreign_keys,
            },
        )

    def get_context_description(self) -> str:
        """Generate a text description for LLM prompt injection."""
        lines = [
            f"Database: {self._display_name}",
            f"Source ID: {self._source_id}",
            f"Tables ({len(self._tables)}):",
        ]
        for table in self._tables:
            size_tag = self._size_tags.get(table.name, TableSizeTag.MEDIUM)
            row_str = f"{table.row_count:,}" if table.row_count is not None else "?"
            lines.append(f"  - {table.name} ({row_str} rows, {size_tag.value})")

            for col in table.columns:
                nullable = "NULL" if col.nullable else "NOT NULL"
                pk = " PK" if col.name in table.primary_keys else ""
                lines.append(f"      {col.name}: {col.dtype} {nullable}{pk}")

        if self._foreign_keys:
            lines.append("Foreign Keys:")
            for fk in self._foreign_keys:
                src = f"{fk['source_table']}.{','.join(fk['source_columns'])}"
                tgt = f"{fk['target_table']}.{','.join(fk['target_columns'])}"
                lines.append(f"  - {src} → {tgt}")

        lines.append(f"SQL syntax: {self._connector.dialect.__class__.__name__}")
        return "\n".join(lines)

    def get_relationships(self) -> list[dict]:
        return self._foreign_keys

    def execute_query(self, query: str, max_rows: int = 100) -> pd.DataFrame:
        return self._connector.execute_query(query, max_rows=max_rows)

    def get_sample(self, table_name: str, limit: int = 5) -> pd.DataFrame:
        quoted = self._connector.dialect.quote_identifier(table_name)
        schema = None
        for t in self._tables:
            if t.name == table_name:
                schema = t.schema
                break
        if schema:
            quoted = f"{self._connector.dialect.quote_identifier(schema)}.{quoted}"
        query = f"SELECT * FROM {quoted}"
        query = self._connector.dialect.add_limit(query, limit)
        return self._connector.execute_query(query, max_rows=limit)

    def close(self) -> None:
        if not self._closed:
            self._connector.close()
            self._closed = True
            logger.info("Disconnected from %s", self._display_name)
