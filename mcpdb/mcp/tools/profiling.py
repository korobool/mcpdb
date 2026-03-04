"""Profiling MCP tools — profile_table, profile_column."""

from __future__ import annotations

import logging
from typing import Any

from mcp.types import TextContent, Tool

from mcpdb.sources.base import QueryableSource
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.mcp.profiling")

_TOOLS = [
    Tool(
        name="profile_table",
        description=(
            "Profile a table: row count, column statistics (nulls, distinct values, "
            "min/max), size classification, and index information."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
                "table_name": {"type": "string", "description": "Table to profile"},
                "sample_size": {
                    "type": "integer",
                    "default": 10000,
                    "description": "Max rows to sample for statistics (0 = full scan)",
                },
            },
            "required": ["source_id", "table_name"],
        },
    ),
    Tool(
        name="profile_column",
        description=(
            "Profile a specific column: data type, nulls, distinct values, "
            "top values by frequency, min/max, and basic distribution."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
                "table_name": {"type": "string"},
                "column_name": {"type": "string", "description": "Column to profile"},
                "top_n": {
                    "type": "integer",
                    "default": 10,
                    "description": "Number of top values to return",
                },
            },
            "required": ["source_id", "table_name", "column_name"],
        },
    ),
]


def get_profiling_tools() -> list[Tool]:
    return list(_TOOLS)


def handle_profiling_tool(
    name: str, args: dict[str, Any], registry: SourceRegistry
) -> list[TextContent]:
    if name == "profile_table":
        return _profile_table(registry, args)
    elif name == "profile_column":
        return _profile_column(registry, args)
    return [TextContent(type="text", text=f"Unknown profiling tool: {name}")]


def _get_queryable_source(
    registry: SourceRegistry, source_id: str
) -> QueryableSource:
    source = registry.get_source(source_id)
    if not isinstance(source, QueryableSource):
        raise ValueError(f"Source '{source_id}' does not support SQL queries")
    return source


def _qualify_table(source: QueryableSource, table_name: str) -> str:
    """Return schema-qualified, quoted table name."""
    dialect = source.dialect  # type: ignore[attr-defined]
    quoted = dialect.quote_identifier(table_name)
    # Find schema for this table
    for t in source.get_tables():
        if t.name == table_name and t.schema:
            return f"{dialect.quote_identifier(t.schema)}.{quoted}"
    return quoted


def _profile_table(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    source = _get_queryable_source(registry, args["source_id"])
    table_name = args["table_name"]
    sample_size = args.get("sample_size", 10000)

    # Verify table exists
    tables = source.get_tables()
    table_info = None
    for t in tables:
        if t.name == table_name:
            table_info = t
            break
    if table_info is None:
        return [TextContent(type="text", text=f"Table '{table_name}' not found.")]

    qualified = _qualify_table(source, table_name)
    lines = [f"## Profile: {table_name}"]

    # Row count
    row_count = table_info.row_count
    if row_count is not None:
        lines.append(f"Row count: {row_count:,}")

    # Primary keys
    if table_info.primary_keys:
        lines.append(f"Primary keys: {', '.join(table_info.primary_keys)}")

    # Indexes
    if table_info.indexes:
        idx_strs = []
        for idx in table_info.indexes:
            unique = " (unique)" if idx.get("unique") else ""
            cols = ", ".join(idx.get("columns", []))
            idx_strs.append(f"  {idx.get('name', '?')}: [{cols}]{unique}")
        lines.append("Indexes:")
        lines.extend(idx_strs)

    # Column statistics via SQL
    col_names = [c.name for c in table_info.columns]
    try:
        stats = _compute_column_stats(source, qualified, col_names, sample_size)
        lines.append("")
        lines.append(f"{'Column':<30} {'Type':<15} {'Nulls':<8} {'Distinct':<10} {'Min':<20} {'Max':<20}")
        lines.append("-" * 103)
        for col in table_info.columns:
            s = stats.get(col.name, {})
            null_count = s.get("nulls", "?")
            distinct = s.get("distinct", "?")
            min_val = _truncate(str(s.get("min", "")), 20)
            max_val = _truncate(str(s.get("max", "")), 20)
            lines.append(
                f"{col.name:<30} {col.dtype:<15} {str(null_count):<8} "
                f"{str(distinct):<10} {min_val:<20} {max_val:<20}"
            )
    except Exception as e:
        logger.warning("Failed to compute column stats for %s: %s", table_name, e)
        lines.append(f"\n(Column statistics unavailable: {e})")

    return [TextContent(type="text", text="\n".join(lines))]


def _compute_column_stats(
    source: QueryableSource,
    qualified_table: str,
    columns: list[str],
    sample_size: int,
) -> dict[str, dict[str, Any]]:
    """Compute basic stats for each column using a single SQL query."""
    dialect = source.dialect  # type: ignore[attr-defined]

    # Build aggregate expressions
    agg_parts = []
    for col_name in columns:
        qcol = dialect.quote_identifier(col_name)
        agg_parts.append(f"COUNT(*) - COUNT({qcol}) AS nulls_{col_name}")
        agg_parts.append(f"COUNT(DISTINCT {qcol}) AS distinct_{col_name}")
        agg_parts.append(f"MIN(CAST({qcol} AS TEXT)) AS min_{col_name}")
        agg_parts.append(f"MAX(CAST({qcol} AS TEXT)) AS max_{col_name}")

    select_clause = ", ".join(agg_parts)

    if sample_size > 0:
        query = f"SELECT {select_clause} FROM (SELECT * FROM {qualified_table} {dialect.add_limit('', sample_size).strip()}) _sample"
        # Fallback: some dialects don't support subquery with LIMIT well
        try:
            df = source.execute_query(query, max_rows=1)
        except Exception:
            query = f"SELECT {select_clause} FROM {qualified_table}"
            df = source.execute_query(query, max_rows=1)
    else:
        query = f"SELECT {select_clause} FROM {qualified_table}"
        df = source.execute_query(query, max_rows=1)

    if df.empty:
        return {}

    row = df.iloc[0]
    stats: dict[str, dict[str, Any]] = {}
    for col_name in columns:
        stats[col_name] = {
            "nulls": _safe_int(row.get(f"nulls_{col_name}")),
            "distinct": _safe_int(row.get(f"distinct_{col_name}")),
            "min": row.get(f"min_{col_name}", ""),
            "max": row.get(f"max_{col_name}", ""),
        }
    return stats


def _profile_column(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    source = _get_queryable_source(registry, args["source_id"])
    table_name = args["table_name"]
    column_name = args["column_name"]
    top_n = args.get("top_n", 10)

    # Verify table and column exist
    tables = source.get_tables()
    table_info = None
    col_info = None
    for t in tables:
        if t.name == table_name:
            table_info = t
            for c in t.columns:
                if c.name == column_name:
                    col_info = c
                    break
            break

    if table_info is None:
        return [TextContent(type="text", text=f"Table '{table_name}' not found.")]
    if col_info is None:
        return [TextContent(type="text", text=f"Column '{column_name}' not found in '{table_name}'.")]

    dialect = source.dialect  # type: ignore[attr-defined]
    qualified = _qualify_table(source, table_name)
    qcol = dialect.quote_identifier(column_name)

    lines = [f"## Column Profile: {table_name}.{column_name}"]
    lines.append(f"Type: {col_info.dtype}")
    lines.append(f"Nullable: {col_info.nullable}")

    # Basic stats
    try:
        stats_query = (
            f"SELECT "
            f"COUNT(*) AS total, "
            f"COUNT({qcol}) AS non_null, "
            f"COUNT(*) - COUNT({qcol}) AS null_count, "
            f"COUNT(DISTINCT {qcol}) AS distinct_count, "
            f"MIN(CAST({qcol} AS TEXT)) AS min_val, "
            f"MAX(CAST({qcol} AS TEXT)) AS max_val "
            f"FROM {qualified}"
        )
        df = source.execute_query(stats_query, max_rows=1)
        if not df.empty:
            row = df.iloc[0]
            total = _safe_int(row.get("total", 0))
            null_count = _safe_int(row.get("null_count", 0))
            distinct = _safe_int(row.get("distinct_count", 0))
            null_pct = f"{(null_count / total * 100):.1f}%" if total > 0 else "N/A"
            lines.append(f"Total rows: {total:,}")
            lines.append(f"Null count: {null_count:,} ({null_pct})")
            lines.append(f"Distinct values: {distinct:,}")
            lines.append(f"Min: {row.get('min_val', 'N/A')}")
            lines.append(f"Max: {row.get('max_val', 'N/A')}")
    except Exception as e:
        lines.append(f"(Basic stats unavailable: {e})")

    # Top values by frequency
    try:
        top_query = (
            f"SELECT CAST({qcol} AS TEXT) AS value, COUNT(*) AS frequency "
            f"FROM {qualified} "
            f"WHERE {qcol} IS NOT NULL "
            f"GROUP BY CAST({qcol} AS TEXT) "
            f"ORDER BY COUNT(*) DESC"
        )
        top_query = dialect.add_limit(top_query, top_n)
        df_top = source.execute_query(top_query, max_rows=top_n)
        if not df_top.empty:
            lines.append(f"\nTop {len(df_top)} values:")
            for _, row in df_top.iterrows():
                val = _truncate(str(row.get("value", "")), 40)
                freq = row.get("frequency", 0)
                lines.append(f"  {val}: {freq:,}")
    except Exception as e:
        lines.append(f"\n(Top values unavailable: {e})")

    return [TextContent(type="text", text="\n".join(lines))]


def _safe_int(val: Any) -> int | str:
    """Convert a value to int safely."""
    if val is None:
        return "?"
    try:
        return int(val)
    except (ValueError, TypeError):
        return "?"


def _truncate(s: str, length: int) -> str:
    """Truncate a string with ellipsis."""
    if len(s) <= length:
        return s
    return s[: length - 3] + "..."
