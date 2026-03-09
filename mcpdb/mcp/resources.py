"""MCP resources — schema, ERD, session state."""

from __future__ import annotations

import json
import logging
import re
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
    """Build a Mermaid ER diagram with explicit FKs + inferred relationships.

    Combines declared foreign keys with heuristic-inferred relationships
    (from column naming patterns like ``order_id`` → ``orders.id``).
    Marks FK columns in table definitions and labels relationship lines
    with the joining column name.
    """
    from mcpdb.mcp.tools.relationships import _infer_relationships

    # --- Merge explicit + inferred, deduplicate --------------------------
    all_rels = list(relationships)
    for rel in all_rels:
        rel.setdefault("type", "foreign_key")

    inferred = _infer_relationships(tables)

    explicit_keys: set[tuple[str, str, str, str]] = set()
    for rel in all_rels:
        src_cols = rel.get("source_columns", [])
        tgt_cols = rel.get("target_columns", [])
        if src_cols and tgt_cols:
            explicit_keys.add((
                rel["source_table"], src_cols[0],
                rel["target_table"], tgt_cols[0],
            ))

    for rel in inferred:
        key = (
            rel["source_table"], rel["source_columns"][0],
            rel["target_table"], rel["target_columns"][0],
        )
        if key not in explicit_keys:
            all_rels.append(rel)
            explicit_keys.add(key)

    # --- Build FK column index (table.col → target info) -----------------
    fk_columns: dict[tuple[str, str], str] = {}  # (table, col) → target_table
    for rel in all_rels:
        src_tbl = rel["source_table"]
        for col_name in rel.get("source_columns", []):
            fk_columns[(src_tbl, col_name)] = rel["target_table"]

    # --- Table names present in the schema -------------------------------
    table_names = {t.name for t in tables}

    # --- Render tables with PK/FK markers --------------------------------
    lines = ["erDiagram"]
    for table in tables:
        safe_table = _sanitize_mermaid_name(table.name)
        lines.append(f"    {safe_table} {{")
        for i, col in enumerate(table.columns):
            is_pk = col.name in table.primary_keys
            is_fk = (table.name, col.name) in fk_columns
            marker = "PK" if is_pk else ("FK" if is_fk else "")
            dtype = _sanitize_mermaid_type(col.dtype)
            safe_name = _sanitize_mermaid_name(col.name)
            lines.append(f"        {dtype} {safe_name} {marker}".rstrip())
            if i >= 9:
                remaining = len(table.columns) - 10
                lines.append(f"        string _{remaining}_more_columns_ \"\"")
                break
        lines.append("    }")

    # --- Render relationships with labels --------------------------------
    seen_edges: set[tuple[str, str]] = set()
    for rel in all_rels:
        src = rel["source_table"]
        tgt = rel["target_table"]
        # Only render if both tables exist in the schema
        if src not in table_names or tgt not in table_names:
            continue
        # Deduplicate edges (keep first per table pair direction)
        edge_key = (src, tgt)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)

        # Label: the FK column name
        src_cols = rel.get("source_columns", [])
        label = _sanitize_mermaid_label(src_cols[0]) if src_cols else ""

        # Cardinality: parent ||--o{ child (one-to-many)
        # Use dotted line for inferred relationships
        rel_type = rel.get("type", "foreign_key")
        connector = "||..o{" if rel_type == "inferred" else "||--o{"
        safe_src = _sanitize_mermaid_name(src)
        safe_tgt = _sanitize_mermaid_name(tgt)
        lines.append(f'    {safe_tgt} {connector} {safe_src} : "{label}"')

    return "\n".join(lines)


def _sanitize_mermaid_name(name: str) -> str:
    """Sanitize a table or column name for mermaid ER diagram identifiers.

    Mermaid erDiagram identifiers must be alphanumeric (plus underscores).
    Spaces, parentheses, quotes, hyphens, and other special characters
    cause parse errors.  E.g. ``Order Date (UTC)`` → ``Order_Date_UTC``.
    """
    # Replace spaces and hyphens with underscores
    name = name.replace(" ", "_").replace("-", "_")
    # Remove all characters that aren't alphanumeric or underscore
    name = re.sub(r"[^A-Za-z0-9_]", "", name)
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name)
    return name or "unnamed"


def _sanitize_mermaid_label(label: str) -> str:
    """Sanitize a relationship label for mermaid ER diagram.

    Labels appear inside double quotes, so we only need to escape
    quotes and remove characters that could break the mermaid parser.
    """
    label = label.replace('"', "'")
    label = label.replace(" ", "_").replace("-", "_")
    # Remove problematic chars but keep underscores and alphanumerics
    label = re.sub(r"[^A-Za-z0-9_]", "", label)
    label = re.sub(r"_+", "_", label)
    return label


def _sanitize_mermaid_type(dtype: str) -> str:
    """Sanitize a SQL type for mermaid ER diagram compatibility.

    Mermaid attribute types cannot contain parentheses, commas, or spaces.
    E.g. ``VARCHAR(255)`` → ``VARCHAR``, ``NUMERIC(10, 2)`` → ``NUMERIC``.
    """
    # Strip parenthesized suffixes: VARCHAR(255) → VARCHAR
    paren = dtype.find("(")
    if paren != -1:
        dtype = dtype[:paren]
    # Replace spaces with underscores: DOUBLE PRECISION → DOUBLE_PRECISION
    dtype = dtype.strip().replace(" ", "_")
    return dtype or "unknown"
