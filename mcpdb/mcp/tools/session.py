"""Session management MCP tools — connect, list, remove, get schema."""

from __future__ import annotations

import logging
from typing import Any

from mcp.types import TextContent, Tool

from mcpdb.sources.registry import SourceNotFoundError, SourceRegistry

logger = logging.getLogger("mcpdb.mcp.session")

_TOOLS = [
    Tool(
        name="connect_database",
        description=(
            "Connect to a SQL database. Supports PostgreSQL, MySQL, "
            "SQLite, SQL Server, Oracle."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "connection_string": {
                    "type": "string",
                    "description": "SQLAlchemy connection string",
                },
                "display_name": {
                    "type": "string",
                    "description": "Human-readable name (optional)",
                },
            },
            "required": ["connection_string"],
        },
    ),
    Tool(
        name="list_sources",
        description="List all connected data sources.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="remove_source",
        description="Disconnect a data source.",
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string", "description": "Source ID to disconnect"},
            },
            "required": ["source_id"],
        },
    ),
    Tool(
        name="get_source_schema",
        description="Get the full schema description of a data source.",
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string", "description": "Source ID"},
            },
            "required": ["source_id"],
        },
    ),
    Tool(
        name="get_session_status",
        description="Get the current session status including active sources and session metadata.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "default": "default",
                    "description": "Session ID (optional)",
                },
            },
        },
    ),
    Tool(
        name="load_csv_files",
        description=(
            "Load one or more CSV files for SQL querying. "
            "Auto-detects encoding, delimiters, and headers. "
            "Files are loaded into DuckDB and can be joined via SQL."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Path(s) to CSV files",
                    "minItems": 1,
                },
                "table_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional table names (one per file)",
                },
                "display_name": {
                    "type": "string",
                    "description": "Human-readable name for this source (optional)",
                },
            },
            "required": ["file_paths"],
        },
    ),
]


def get_session_tools() -> list[Tool]:
    return list(_TOOLS)


def handle_session_tool(
    name: str, args: dict[str, Any], registry: SourceRegistry
) -> list[TextContent]:
    if name == "connect_database":
        return _connect_database(registry, args)
    elif name == "list_sources":
        return _list_sources(registry)
    elif name == "remove_source":
        return _remove_source(registry, args)
    elif name == "get_source_schema":
        return _get_source_schema(registry, args)
    elif name == "get_session_status":
        return _get_session_status(registry, args)
    elif name == "load_csv_files":
        return _load_csv_files(registry, args)
    return [TextContent(type="text", text=f"Unknown session tool: {name}")]


def _connect_database(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    from mcpdb.sources.database.source import DatabaseSource

    source = DatabaseSource(
        args["connection_string"],
        display_name=args.get("display_name"),
    )
    source_id = registry.add_source(source)
    meta = source.get_metadata()

    table_list = "\n".join(
        f"  - {t.name} ({t.row_count or '?'} rows, {len(t.columns)} columns)"
        for t in meta.tables
    )

    return [TextContent(
        type="text",
        text=(
            f"Connected: {meta.display_name}\n"
            f"Source ID: {source_id}\n"
            f"Tables ({len(meta.tables)}):\n{table_list}"
        ),
    )]


def _list_sources(registry: SourceRegistry) -> list[TextContent]:
    sources = registry.list_sources()
    if not sources:
        return [TextContent(type="text", text="No data sources connected.")]

    lines = [
        f"- {m.source_id} ({m.source_type.value}): {m.display_name} — {len(m.tables)} tables"
        for m in sources
    ]
    return [TextContent(type="text", text="\n".join(lines))]


def _remove_source(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    try:
        registry.remove_source(args["source_id"])
        return [TextContent(type="text", text=f"Disconnected: {args['source_id']}")]
    except SourceNotFoundError:
        return [TextContent(type="text", text=f"Error: Source '{args['source_id']}' not found")]


def _get_source_schema(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    try:
        source = registry.get_source(args["source_id"])
        return [TextContent(type="text", text=source.get_context_description())]
    except SourceNotFoundError:
        return [TextContent(type="text", text=f"Error: Source '{args['source_id']}' not found")]


def _get_session_status(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    sources = registry.list_sources()
    lines = ["## Session Status"]
    lines.append(f"Active sources: {len(sources)}")

    for m in sources:
        table_count = len(m.tables)
        total_rows = sum(t.row_count or 0 for t in m.tables)
        lines.append(f"  - {m.source_id} ({m.source_type.value}): {m.display_name}")
        lines.append(f"    Tables: {table_count}, Rows: {total_rows:,}")
        lines.append(f"    Capabilities: {', '.join(sorted(m.capabilities))}")

    return [TextContent(type="text", text="\n".join(lines))]


def _load_csv_files(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    from mcpdb.sources.csv.source import CsvSource

    file_paths = args["file_paths"]
    table_names = args.get("table_names")
    display_name = args.get("display_name")

    try:
        source = CsvSource(
            file_paths=file_paths,
            display_name=display_name,
            table_names=table_names,
        )
        source_id = registry.add_source(source)
        meta = source.get_metadata()

        table_list = "\n".join(
            f"  - {t.name} ({t.row_count or '?'} rows, {len(t.columns)} columns)"
            for t in meta.tables
        )

        return [TextContent(
            type="text",
            text=(
                f"Loaded CSV: {meta.display_name}\n"
                f"Source ID: {source_id}\n"
                f"Tables ({len(meta.tables)}):\n{table_list}\n"
                f"Query with SQL using the table names above."
            ),
        )]
    except Exception as e:
        logger.error("Failed to load CSV files: %s", e, exc_info=True)
        return [TextContent(type="text", text=f"Error loading CSV: {e}")]
