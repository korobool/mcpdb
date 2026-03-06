"""Relationship MCP tools — find_relationships, suggest_joins."""

from __future__ import annotations

import logging
from typing import Any

from mcp.types import TextContent, Tool

from mcpdb.sources.base import QueryableSource, TableInfo
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.mcp.relationships")

_TOOLS = [
    Tool(
        name="find_relationships",
        description=(
            "Discover relationships between tables: explicit foreign keys plus "
            "inferred joins based on column name and type matching."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
                "table_name": {
                    "type": "string",
                    "description": "Optional: filter to relationships involving this table",
                },
            },
            "required": ["source_id"],
        },
    ),
    Tool(
        name="suggest_joins",
        description=(
            "Suggest SQL JOIN conditions for a set of tables based on "
            "foreign keys and inferred column relationships."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
                "tables": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Table names to join (2 or more)",
                    "minItems": 2,
                },
            },
            "required": ["source_id", "tables"],
        },
    ),
]


def get_relationship_tools() -> list[Tool]:
    return list(_TOOLS)


def handle_relationship_tool(
    name: str, args: dict[str, Any], registry: SourceRegistry
) -> list[TextContent]:
    if name == "find_relationships":
        return _find_relationships(registry, args)
    elif name == "suggest_joins":
        return _suggest_joins(registry, args)
    return [TextContent(type="text", text=f"Unknown relationship tool: {name}")]


# Common naming patterns that suggest FK relationships
_FK_SUFFIXES = ("_id", "_fk", "_key", "_ref", "id", "Id", "ID")
_FK_PREFIXES = ("fk_", "ref_")


def _infer_relationships(tables: list[TableInfo]) -> list[dict[str, Any]]:
    """Infer join relationships from column name/type matching.

    Heuristics:
    1. Column named `{other_table}_id` or `{other_table}id` → likely FK
    2. Column with ``_id`` suffix matching a table name
    3. Column name exactly matches a single-column PK of another table
       (handles prefixed tables, e.g. ``opis_id`` → ``ins_opis.opis_id``)
    """
    table_map = {t.name: t for t in tables}
    # Build index of table PKs
    pk_map: dict[str, set[str]] = {}
    for t in tables:
        if t.primary_keys:
            pk_map[t.name] = set(t.primary_keys)

    # Reverse index: PK column name → tables that have it as sole PK
    pk_col_to_tables: dict[str, list[str]] = {}
    for tname, pks in pk_map.items():
        if len(pks) == 1:
            pk_col = next(iter(pks))
            pk_col_to_tables.setdefault(pk_col, []).append(tname)

    inferred: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    def _add(src_table: str, src_col: str, tgt_table: str, tgt_col: str,
             confidence: str = "high") -> None:
        key = (src_table, src_col, tgt_table, tgt_col)
        if key not in seen:
            seen.add(key)
            inferred.append({
                "source_table": src_table,
                "source_columns": [src_col],
                "target_table": tgt_table,
                "target_columns": [tgt_col],
                "type": "inferred",
                "confidence": confidence,
            })

    def _resolve_pk(other_name: str) -> str | None:
        """Return the single PK column for a table, or 'id' fallback."""
        if other_name in pk_map and len(pk_map[other_name]) == 1:
            return next(iter(pk_map[other_name]))
        other_table = table_map[other_name]
        for tc in other_table.columns:
            if tc.name.lower() == "id":
                return tc.name
        return None

    for table in tables:
        for col in table.columns:
            col_lower = col.name.lower()

            # Pattern 1: column named <table>_id or <table>id
            for other_name in table_map:
                if other_name == table.name:
                    continue
                other_lower = other_name.lower()

                patterns = [
                    f"{other_lower}_id",
                    f"{other_lower}id",
                    f"{other_lower}_fk",
                ]
                if other_lower.endswith("s"):
                    singular = other_lower[:-1]
                    patterns.extend([f"{singular}_id", f"{singular}id"])

                if col_lower in patterns:
                    target_col = _resolve_pk(other_name)
                    if target_col:
                        _add(table.name, col.name, other_name, target_col)

            # Pattern 2: column ends with _id and matches a table name
            if col_lower.endswith("_id"):
                prefix = col_lower[:-3]  # strip "_id"
                for other_name in table_map:
                    if other_name == table.name:
                        continue
                    other_lower = other_name.lower()
                    if prefix == other_lower or (
                        other_lower.endswith("s") and prefix == other_lower[:-1]
                    ):
                        target_col = _resolve_pk(other_name)
                        if target_col:
                            _add(table.name, col.name, other_name, target_col)

            # Pattern 3: column name matches a single-column PK of another table
            # e.g. ins_opis_rows.opis_id → ins_opis.opis_id (PK)
            if col.name in pk_col_to_tables:
                for owner_table in pk_col_to_tables[col.name]:
                    if owner_table == table.name:
                        continue
                    # Skip if this column IS the PK of the current table
                    if table.name in pk_map and col.name in pk_map[table.name]:
                        continue
                    _add(table.name, col.name, owner_table, col.name,
                         confidence="medium")

    return inferred


def _find_relationships(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    source = registry.get_source(args["source_id"])
    table_filter = args.get("table_name")
    tables = source.get_tables()

    # Explicit FKs
    explicit = source.get_relationships()
    for fk in explicit:
        fk["type"] = "foreign_key"

    # Inferred relationships
    inferred = _infer_relationships(tables)

    # Deduplicate: remove inferred if same relationship exists as FK
    explicit_set = set()
    for fk in explicit:
        key = (fk["source_table"], tuple(fk["source_columns"]),
               fk["target_table"], tuple(fk["target_columns"]))
        explicit_set.add(key)

    unique_inferred = []
    for inf in inferred:
        key = (inf["source_table"], tuple(inf["source_columns"]),
               inf["target_table"], tuple(inf["target_columns"]))
        if key not in explicit_set:
            unique_inferred.append(inf)

    all_rels = explicit + unique_inferred

    # Filter by table name if specified
    if table_filter:
        all_rels = [
            r for r in all_rels
            if r["source_table"] == table_filter or r["target_table"] == table_filter
        ]

    if not all_rels:
        msg = "No relationships found"
        if table_filter:
            msg += f" for table '{table_filter}'"
        return [TextContent(type="text", text=msg + ".")]

    lines = [f"## Relationships ({len(all_rels)} found)"]
    for rel in all_rels:
        src_cols = ", ".join(rel["source_columns"])
        tgt_cols = ", ".join(rel["target_columns"])
        rel_type = rel.get("type", "unknown")
        badge = "FK" if rel_type == "foreign_key" else "INFERRED"
        lines.append(
            f"[{badge}] {rel['source_table']}.({src_cols}) → "
            f"{rel['target_table']}.({tgt_cols})"
        )

    return [TextContent(type="text", text="\n".join(lines))]


def _suggest_joins(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    source = registry.get_source(args["source_id"])
    table_names = args["tables"]
    tables = source.get_tables()

    # Validate table names
    table_set = {t.name for t in tables}
    invalid = [t for t in table_names if t not in table_set]
    if invalid:
        return [TextContent(
            type="text",
            text=f"Tables not found: {', '.join(invalid)}",
        )]

    # Collect all relationships (explicit + inferred)
    explicit = source.get_relationships()
    for fk in explicit:
        fk["type"] = "foreign_key"
    inferred = _infer_relationships(tables)

    all_rels = explicit + inferred
    requested = set(table_names)

    # Find relationships that connect requested tables
    relevant = []
    for rel in all_rels:
        if rel["source_table"] in requested and rel["target_table"] in requested:
            relevant.append(rel)

    if not relevant:
        return [TextContent(
            type="text",
            text=f"No join paths found between {', '.join(table_names)}.",
        )]

    # Build JOIN suggestions
    lines = [f"## Suggested Joins for: {', '.join(table_names)}"]

    # Deduplicate
    seen: set[tuple] = set()
    for rel in relevant:
        key = (rel["source_table"], tuple(rel["source_columns"]),
               rel["target_table"], tuple(rel["target_columns"]))
        if key in seen:
            continue
        seen.add(key)

        # Build ON clause
        on_parts = []
        for sc, tc in zip(rel["source_columns"], rel["target_columns"]):
            on_parts.append(f"{rel['source_table']}.{sc} = {rel['target_table']}.{tc}")

        rel_type = "FK" if rel.get("type") == "foreign_key" else "INFERRED"
        lines.append(f"\n[{rel_type}] JOIN {rel['target_table']}")
        lines.append(f"  ON {' AND '.join(on_parts)}")

    # Build a complete SQL example
    if len(table_names) >= 2:
        lines.append("\n### Example SQL:")
        base = table_names[0]
        join_clauses = []
        joined = {base}

        for rel in relevant:
            key = (rel["source_table"], tuple(rel["source_columns"]),
                   rel["target_table"], tuple(rel["target_columns"]))
            src, tgt = rel["source_table"], rel["target_table"]
            if src in joined and tgt not in joined:
                on_parts = [
                    f"{src}.{sc} = {tgt}.{tc}"
                    for sc, tc in zip(rel["source_columns"], rel["target_columns"])
                ]
                join_clauses.append(f"  JOIN {tgt} ON {' AND '.join(on_parts)}")
                joined.add(tgt)
            elif tgt in joined and src not in joined:
                on_parts = [
                    f"{tgt}.{tc} = {src}.{sc}"
                    for sc, tc in zip(rel["source_columns"], rel["target_columns"])
                ]
                join_clauses.append(f"  JOIN {src} ON {' AND '.join(on_parts)}")
                joined.add(src)

        if join_clauses:
            lines.append(f"SELECT *\nFROM {base}")
            lines.extend(join_clauses)

    return [TextContent(type="text", text="\n".join(lines))]
