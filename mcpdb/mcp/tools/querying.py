"""Query execution MCP tools — execute_sql, get_table_sample, validate_sql."""

from __future__ import annotations

import logging
from typing import Any

from mcp.types import TextContent, Tool

from mcpdb.sources.base import QueryableSource
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.mcp.querying")

_TOOLS = [
    Tool(
        name="execute_sql",
        description="Execute a SQL query on a connected data source.",
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string", "description": "Source ID to query"},
                "sql": {"type": "string", "description": "SQL query to execute"},
                "max_rows": {
                    "type": "integer",
                    "description": "Maximum rows to return (default: 100)",
                    "default": 100,
                },
            },
            "required": ["source_id", "sql"],
        },
    ),
    Tool(
        name="get_table_sample",
        description="Get sample rows from a table.",
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
                "table": {"type": "string", "description": "Table name"},
                "n": {"type": "integer", "description": "Number of rows (default: 5)", "default": 5},
            },
            "required": ["source_id", "table"],
        },
    ),
    Tool(
        name="validate_sql",
        description="Check if a SQL query is syntactically valid without executing it.",
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
                "sql": {"type": "string", "description": "SQL to validate"},
            },
            "required": ["source_id", "sql"],
        },
    ),
    Tool(
        name="cross_source_query",
        description=(
            "Execute a SQL query spanning multiple data sources. "
            "Tables from different sources are automatically federated "
            "via DuckDB. Reference tables by their original names."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SQL query referencing tables from multiple sources"},
                "source_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Source IDs involved in the query",
                    "minItems": 2,
                },
                "max_rows": {
                    "type": "integer",
                    "default": 100,
                    "description": "Maximum rows to return",
                },
            },
            "required": ["sql", "source_ids"],
        },
    ),
]


def get_query_tools() -> list[Tool]:
    return list(_TOOLS)


def handle_query_tool(
    name: str, args: dict[str, Any], registry: SourceRegistry
) -> list[TextContent]:
    if name == "execute_sql":
        return _execute_sql(registry, args)
    elif name == "get_table_sample":
        return _get_table_sample(registry, args)
    elif name == "validate_sql":
        return _validate_sql(registry, args)
    elif name == "cross_source_query":
        return _cross_source_query(registry, args)
    return [TextContent(type="text", text=f"Unknown query tool: {name}")]


def _get_queryable(registry: SourceRegistry, source_id: str) -> QueryableSource:
    source = registry.get_source(source_id)
    if not isinstance(source, QueryableSource):
        raise ValueError(f"Source '{source_id}' does not support SQL queries")
    return source


def _df_to_text(df: Any) -> str:
    """Convert DataFrame to readable text table."""
    text = df.to_string(max_colwidth=50)
    truncated = df.attrs.get("mcpdb_truncated", False)
    if truncated:
        text += f"\n\n(Results truncated. Showing {len(df)} rows.)"
    return text


def _execute_sql(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    source = _get_queryable(registry, args["source_id"])
    max_rows = args.get("max_rows", 100)
    df = source.execute_query(args["sql"], max_rows=max_rows)

    if df.empty:
        return [TextContent(type="text", text="Query returned no results.")]
    return [TextContent(type="text", text=_df_to_text(df))]


def _get_table_sample(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    source = _get_queryable(registry, args["source_id"])
    df = source.get_sample(args["table"], limit=args.get("n", 5))

    if df.empty:
        return [TextContent(type="text", text="Table is empty.")]
    return [TextContent(type="text", text=_df_to_text(df))]


def _validate_sql(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    source = _get_queryable(registry, args["source_id"])
    sql = args["sql"]

    try:
        dialect = source.dialect if hasattr(source, "dialect") else None
        if dialect:
            connector = source.connector if hasattr(source, "connector") else None
            if connector:
                prefix = dialect.get_explain_prefix()
                connector.execute_raw(f"{prefix} {sql}")
                return [TextContent(type="text", text="Valid SQL.")]

        source.execute_query(f"SELECT * FROM ({sql}) _v LIMIT 0", max_rows=0)
        return [TextContent(type="text", text="Valid SQL.")]
    except Exception as e:
        return [TextContent(type="text", text=f"Invalid SQL: {e}")]


def _cross_source_query(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    from mcpdb.sources.federation import execute_cross_source_query

    sql = args["sql"]
    source_ids = args["source_ids"]
    max_rows = args.get("max_rows", 100)

    try:
        df = execute_cross_source_query(sql, source_ids, registry, max_rows)
        if df.empty:
            return [TextContent(type="text", text="Cross-source query returned no results.")]
        return [TextContent(type="text", text=_df_to_text(df))]
    except Exception as e:
        logger.error("Cross-source query failed: %s", e, exc_info=True)
        return [TextContent(type="text", text=f"Error: {e}")]
