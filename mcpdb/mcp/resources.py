"""MCP resources — schema, ERD, session state."""

from __future__ import annotations

import json
import logging
from typing import Any

from dataclasses import dataclass

from mcp.server import Server
from mcp.types import Resource, ResourceTemplate


@dataclass
class _ResourceContent:
    """Duck-typed ReadResourceContents for the MCP SDK read_resource handler."""
    content: str
    mime_type: str | None = None
    meta: dict | None = None

from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.mcp.resources")

# URI scheme constants
SCHEMA_SCHEME = "schema"
ERD_SCHEME = "erd"
SESSION_SCHEME = "session"


def register_resources(server: Server, registry: SourceRegistry) -> None:
    """Register MCP resource templates and handlers."""

    @server.list_resource_templates()
    async def list_resource_templates() -> list[ResourceTemplate]:
        return [
            ResourceTemplate(
                name="source_schema",
                uriTemplate="schema://{source_id}",
                description="Full schema JSON for a connected data source",
                mimeType="application/json",
            ),
            ResourceTemplate(
                name="source_erd",
                uriTemplate="erd://{source_id}",
                description="Mermaid ER diagram for a connected data source",
                mimeType="text/plain",
            ),
        ]

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        resources: list[Resource] = []

        # Static session resources
        resources.append(Resource(
            name="session_sources",
            uri="session://sources",
            description="List of all active data sources",
            mimeType="application/json",
        ))
        resources.append(Resource(
            name="session_status",
            uri="session://execution_status",
            description="Current agent execution status",
            mimeType="application/json",
        ))

        # Dynamic per-source resources
        for meta in registry.list_sources():
            sid = meta.source_id
            resources.append(Resource(
                name=f"schema_{sid}",
                uri=f"schema://{sid}",
                description=f"Schema for {meta.display_name}",
                mimeType="application/json",
            ))
            resources.append(Resource(
                name=f"erd_{sid}",
                uri=f"erd://{sid}",
                description=f"ERD for {meta.display_name}",
                mimeType="text/plain",
            ))

        return resources

    @server.read_resource()
    async def read_resource(uri: Any) -> list[_ResourceContent]:
        uri_str = str(uri)
        logger.debug("Reading resource: %s", uri_str)

        # Parse URI
        if "://" in uri_str:
            scheme, path = uri_str.split("://", 1)
        else:
            text = json.dumps({"error": f"Invalid resource URI: {uri_str}"})
            return [_ResourceContent(content=text, mime_type="application/json")]

        if scheme == SESSION_SCHEME:
            text = _read_session_resource(path, registry)
            mime = "application/json"
        elif scheme == SCHEMA_SCHEME:
            text = _read_schema_resource(path, registry)
            mime = "application/json"
        elif scheme == ERD_SCHEME:
            text = _read_erd_resource(path, registry)
            mime = "text/plain"
        else:
            text = json.dumps({"error": f"Unknown resource scheme: {scheme}"})
            mime = "application/json"

        return [_ResourceContent(content=text, mime_type=mime)]


def _read_session_resource(path: str, registry: SourceRegistry) -> str:
    if path == "sources":
        sources = registry.list_sources()
        return json.dumps(
            [m.to_dict() for m in sources],
            indent=2,
            default=str,
        )
    elif path == "execution_status":
        # Import here to avoid circular
        from mcpdb.mcp.tools.control import get_session_state
        state = get_session_state()
        return json.dumps({
            "active": state.get("active", False),
            "current_question": state.get("current_question"),
            "mode": state.get("mode"),
        }, indent=2)
    return json.dumps({"error": f"Unknown session resource: {path}"})


def _read_schema_resource(source_id: str, registry: SourceRegistry) -> str:
    try:
        source = registry.get_source(source_id)
        return source.get_schema_json()
    except KeyError:
        return json.dumps({"error": f"Source '{source_id}' not found"})


def _read_erd_resource(source_id: str, registry: SourceRegistry) -> str:
    try:
        source = registry.get_source(source_id)
        tables = source.get_tables()
        relationships = source.get_relationships()
        return _build_mermaid_erd(tables, relationships)
    except KeyError:
        return json.dumps({"error": f"Source '{source_id}' not found"})


def _build_mermaid_erd(tables: list, relationships: list[dict]) -> str:
    """Build a Mermaid ER diagram string."""
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

    return "\n".join(lines)
