"""Discovery MCP tools — search_schema, explain_query, render_erd."""

from __future__ import annotations

import logging
from typing import Any

from mcp.types import TextContent, Tool

from mcpdb.sources.base import QueryableSource
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.mcp.discovery")

_TOOLS = [
    Tool(
        name="search_schema",
        description="Search for tables and columns matching a keyword.",
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
                "keyword": {"type": "string", "description": "Search keyword (case-insensitive)"},
            },
            "required": ["source_id", "keyword"],
        },
    ),
    Tool(
        name="explain_query",
        description="Show the EXPLAIN plan for a SQL query.",
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
                "sql": {"type": "string", "description": "SQL query to explain"},
            },
            "required": ["source_id", "sql"],
        },
    ),
    Tool(
        name="render_erd",
        description="Generate a Mermaid ER diagram for a data source.",
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
            },
            "required": ["source_id"],
        },
    ),
]


def get_discovery_tools() -> list[Tool]:
    return list(_TOOLS)


def handle_discovery_tool(
    name: str, args: dict[str, Any], registry: SourceRegistry
) -> list[TextContent]:
    if name == "search_schema":
        return _search_schema(registry, args)
    elif name == "explain_query":
        return _explain_query(registry, args)
    elif name == "render_erd":
        return _render_erd(registry, args)
    return [TextContent(type="text", text=f"Unknown discovery tool: {name}")]


def _search_schema(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    source = registry.get_source(args["source_id"])
    keyword = args["keyword"].lower()
    tables = source.get_tables()

    matches = []
    for table in tables:
        table_match = keyword in table.name.lower()
        col_matches = [c for c in table.columns if keyword in c.name.lower()]

        if table_match:
            matches.append(f"Table: {table.name} ({table.row_count or '?'} rows)")
        for col in col_matches:
            matches.append(f"  Column: {table.name}.{col.name} ({col.dtype})")

    if not matches:
        return [TextContent(type="text", text=f"No matches for '{args['keyword']}'.")]
    return [TextContent(type="text", text="\n".join(matches))]


def _explain_query(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    source = registry.get_source(args["source_id"])

    if not hasattr(source, "dialect") or not hasattr(source, "connector"):
        return [TextContent(type="text", text="Error: Source does not support EXPLAIN")]

    dialect = source.dialect
    connector = source.connector
    prefix = dialect.get_explain_prefix()

    rows = connector.execute_raw(f"{prefix} {args['sql']}")
    result = dialect.parse_explain_output(rows)

    lines = [f"EXPLAIN for: {args['sql'][:100]}"]
    if result.estimated_rows is not None:
        lines.append(f"Estimated rows: {result.estimated_rows:,}")
    if result.estimated_cost is not None:
        lines.append(f"Estimated cost: {result.estimated_cost:.1f}")
    lines.append(f"Scan type: {result.scan_type}")
    if result.join_types:
        lines.append(f"Join types: {', '.join(result.join_types)}")
    lines.append(f"Uses index: {result.uses_index}")
    if result.warnings:
        lines.append("Warnings:")
        for w in result.warnings:
            lines.append(f"  - {w}")
    return [TextContent(type="text", text="\n".join(lines))]


def _render_erd(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    source = registry.get_source(args["source_id"])
    tables = source.get_tables()
    relationships = source.get_relationships()

    lines = ["erDiagram"]
    for table in tables:
        lines.append(f"    {table.name} {{")
        for i, col in enumerate(table.columns):
            pk = "PK" if col.name in table.primary_keys else ""
            lines.append(f"        {col.dtype} {col.name} {pk}".rstrip())
            if i >= 9:
                lines.append(f"        ... {len(table.columns) - 10}_more_columns")
                break
        lines.append("    }")

    for rel in relationships:
        src = rel["source_table"]
        tgt = rel["target_table"]
        lines.append(f'    {tgt} ||--o{{ {src} : ""')

    return [TextContent(type="text", text="\n".join(lines))]
