"""Excel MCP tools — load, explore, and query Excel workbooks."""

from __future__ import annotations

import logging
from typing import Any

from mcp.types import TextContent, Tool

from mcpdb.sources.registry import SourceNotFoundError, SourceRegistry

logger = logging.getLogger("mcpdb.mcp.excel")

_TOOLS = [
    Tool(
        name="load_excel",
        description=(
            "Load an Excel workbook (.xlsx/.xls). Automatically detects tables "
            "and text regions. Extracted tables are queryable via SQL."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Excel file",
                },
                "display_name": {
                    "type": "string",
                    "description": "Human-readable name (optional)",
                },
            },
            "required": ["file_path"],
        },
    ),
    Tool(
        name="list_sheets",
        description="List all sheets in a loaded Excel workbook with structure info.",
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string", "description": "Excel source ID"},
            },
            "required": ["source_id"],
        },
    ),
    Tool(
        name="read_range",
        description=(
            "Read a range of cells from an Excel sheet. "
            "Returns formatted text suitable for analysis."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string", "description": "Excel source ID"},
                "sheet": {"type": "string", "description": "Sheet name"},
                "range": {
                    "type": "string",
                    "description": "Excel range (e.g. 'A1:D10'). Omit to read entire sheet.",
                },
                "include_formulas": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include formulas instead of computed values",
                },
            },
            "required": ["source_id", "sheet"],
        },
    ),
    Tool(
        name="extract_excel_table",
        description=(
            "Extract a rectangular region from an Excel sheet as a table. "
            "First row is used as headers."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string", "description": "Excel source ID"},
                "sheet": {"type": "string", "description": "Sheet name"},
                "range": {
                    "type": "string",
                    "description": "Excel range to extract (e.g. 'A1:D10')",
                },
            },
            "required": ["source_id", "sheet", "range"],
        },
    ),
    Tool(
        name="explain_formula",
        description=(
            "Explain Excel formulas in a sheet. Lists all formulas or explains "
            "a specific formula in natural language."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string", "description": "Excel source ID"},
                "sheet": {"type": "string", "description": "Sheet name"},
                "cell": {
                    "type": "string",
                    "description": "Specific cell reference (e.g. 'C5'). Omit to list all formulas.",
                },
            },
            "required": ["source_id", "sheet"],
        },
    ),
]


def get_excel_tools() -> list[Tool]:
    return list(_TOOLS)


def handle_excel_tool(
    name: str, args: dict[str, Any], registry: SourceRegistry, llm: Any = None,
) -> list[TextContent]:
    if name == "load_excel":
        return _load_excel(registry, args)
    elif name == "list_sheets":
        return _list_sheets(registry, args)
    elif name == "read_range":
        return _read_range(registry, args)
    elif name == "extract_excel_table":
        return _extract_excel_table(registry, args)
    elif name == "explain_formula":
        return _explain_formula(registry, args, llm)
    return [TextContent(type="text", text=f"Unknown excel tool: {name}")]


def _load_excel(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    from mcpdb.sources.excel.source import ExcelSource

    file_path = args["file_path"]
    display_name = args.get("display_name")

    try:
        source = ExcelSource(file_path, display_name=display_name)
        source_id = registry.add_source(source)
        meta = source.get_metadata()

        lines = [
            f"Loaded Excel: {meta.display_name}",
            f"Source ID: {source_id}",
            f"Sheets: {len(meta.raw_info.get('sheets', []))}",
        ]

        if meta.tables:
            lines.append(f"\nExtracted Tables ({len(meta.tables)}):")
            for t in meta.tables:
                lines.append(f"  - {t.name} ({t.row_count} rows, {len(t.columns)} cols)")
            lines.append("\nQuery extracted tables with SQL using execute_sql.")

        return [TextContent(type="text", text="\n".join(lines))]
    except Exception as e:
        logger.error("Failed to load Excel: %s", e, exc_info=True)
        return [TextContent(type="text", text=f"Error loading Excel: {e}")]


def _get_excel_source(registry: SourceRegistry, source_id: str) -> Any:
    """Get source and verify it's an ExcelSource."""
    from mcpdb.sources.excel.source import ExcelSource

    source = registry.get_source(source_id)
    if not isinstance(source, ExcelSource):
        raise ValueError(f"Source '{source_id}' is not an Excel source")
    return source


def _list_sheets(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    try:
        source = _get_excel_source(registry, args["source_id"])
        sheets = source.list_sheets()

        lines = [f"## Sheets in {source._display_name}"]
        for s in sheets:
            lines.append(
                f"- {s['name']} ({s.get('max_row', '?')} rows × "
                f"{s.get('max_column', '?')} cols, "
                f"type: {s.get('structure_type', 'unknown')}, "
                f"{s.get('tables', 0)} table(s), "
                f"{s.get('text_regions', 0)} text region(s))"
            )
        return [TextContent(type="text", text="\n".join(lines))]
    except SourceNotFoundError:
        return [TextContent(type="text", text=f"Error: Source '{args['source_id']}' not found")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


def _read_range(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    try:
        source = _get_excel_source(registry, args["source_id"])
        text = source.read_range(
            sheet=args["sheet"],
            range_str=args.get("range"),
            include_formulas=args.get("include_formulas", False),
        )
        return [TextContent(type="text", text=text)]
    except SourceNotFoundError:
        return [TextContent(type="text", text=f"Error: Source '{args['source_id']}' not found")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


def _extract_excel_table(
    registry: SourceRegistry, args: dict[str, Any]
) -> list[TextContent]:
    try:
        source = _get_excel_source(registry, args["source_id"])
        df = source.extract_table(sheet=args["sheet"], table_range=args["range"])

        if df.empty:
            return [TextContent(type="text", text="No data found in the specified range.")]

        lines = [f"Extracted table ({len(df)} rows × {len(df.columns)} cols):"]
        lines.append(df.to_string(index=False, max_rows=50))
        if len(df) > 50:
            lines.append(f"... ({len(df) - 50} more rows)")

        return [TextContent(type="text", text="\n".join(lines))]
    except SourceNotFoundError:
        return [TextContent(type="text", text=f"Error: Source '{args['source_id']}' not found")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


def _explain_formula(
    registry: SourceRegistry, args: dict[str, Any], llm: Any,
) -> list[TextContent]:
    try:
        source = _get_excel_source(registry, args["source_id"])
        formulas = source.get_formulas(args["sheet"])

        cell = args.get("cell")
        if cell:
            # Find specific formula
            match = next((f for f in formulas if f["cell"] == cell.upper()), None)
            if match is None:
                return [TextContent(type="text", text=f"No formula found in cell {cell}.")]

            explanation = _explain_single_formula(match["formula"], llm)
            return [TextContent(
                type="text",
                text=f"Cell {match['cell']}: `{match['formula']}`\n\n{explanation}",
            )]

        # List all formulas
        if not formulas:
            return [TextContent(type="text", text="No formulas found in this sheet.")]

        lines = [f"## Formulas in {args['sheet']} ({len(formulas)} found)"]
        for f in formulas[:50]:
            lines.append(f"- {f['cell']}: `{f['formula']}`")
        if len(formulas) > 50:
            lines.append(f"... ({len(formulas) - 50} more)")

        return [TextContent(type="text", text="\n".join(lines))]
    except SourceNotFoundError:
        return [TextContent(type="text", text=f"Error: Source '{args['source_id']}' not found")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


def _explain_single_formula(formula: str, llm: Any) -> str:
    """Use LLM to explain a formula, or fall back to basic parsing."""
    if llm is not None:
        try:
            import asyncio
            from mcpdb.llm.provider import Message

            prompt = (
                f"Explain this Excel formula in one clear sentence:\n"
                f"`{formula}`\n\n"
                f"Be concise. Just explain what it does."
            )
            loop = asyncio.new_event_loop()
            try:
                text, _usage = loop.run_until_complete(
                    llm.generate(
                        [Message(role="user", content=prompt)],
                        max_tokens=256,
                        temperature=0.0,
                    )
                )
                return text
            finally:
                loop.close()
        except Exception:
            pass

    # Basic fallback: describe the function used
    return _basic_formula_explanation(formula)


def _basic_formula_explanation(formula: str) -> str:
    """Simple rule-based formula explanation."""
    f = formula.upper().lstrip("=")

    known = {
        "SUM": "Sums the values",
        "AVERAGE": "Calculates the average",
        "COUNT": "Counts the number of cells",
        "COUNTA": "Counts non-empty cells",
        "MAX": "Returns the maximum value",
        "MIN": "Returns the minimum value",
        "IF": "Conditional: returns one value if true, another if false",
        "VLOOKUP": "Looks up a value in the first column and returns a value in the same row",
        "HLOOKUP": "Looks up a value in the first row and returns a value in the same column",
        "INDEX": "Returns a value at a given position in a range",
        "MATCH": "Returns the position of a value in a range",
        "SUMIF": "Sums values that meet a condition",
        "COUNTIF": "Counts cells that meet a condition",
        "CONCATENATE": "Joins text strings together",
        "LEFT": "Returns the leftmost characters",
        "RIGHT": "Returns the rightmost characters",
        "MID": "Returns characters from the middle",
        "LEN": "Returns the length of a text string",
        "TRIM": "Removes extra spaces",
        "ROUND": "Rounds a number to specified digits",
    }

    for func, desc in known.items():
        if f.startswith(func + "("):
            # Extract the range argument
            inner = formula[len(func) + 2:-1] if formula.endswith(")") else formula[len(func) + 2:]
            return f"{desc} in {inner}."

    return f"Formula: {formula}"
