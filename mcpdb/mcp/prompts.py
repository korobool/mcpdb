"""MCP prompts — explore_source, deep_table_analysis."""

from __future__ import annotations

import logging

from mcp.server import Server
from mcp.types import (
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    TextContent,
)

from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.mcp.prompts")

_PROMPTS = [
    Prompt(
        name="explore_source",
        description=(
            "Guided multi-step exploration workflow for a connected data source. "
            "Walks through schema overview, table profiling, relationship discovery, "
            "and sample queries."
        ),
        arguments=[
            PromptArgument(
                name="source_id",
                description="The source ID to explore",
                required=True,
            ),
        ],
    ),
    Prompt(
        name="deep_table_analysis",
        description=(
            "In-depth analysis prompt for a specific table. Covers structure, "
            "data quality, distribution patterns, and potential insights."
        ),
        arguments=[
            PromptArgument(
                name="source_id",
                description="The source ID containing the table",
                required=True,
            ),
            PromptArgument(
                name="table_name",
                description="The table to analyze in depth",
                required=True,
            ),
        ],
    ),
]


def register_prompts(server: Server, registry: SourceRegistry) -> None:
    """Register MCP prompts on the server."""

    @server.list_prompts()
    async def list_prompts() -> list[Prompt]:
        return list(_PROMPTS)

    @server.get_prompt()
    async def get_prompt(
        name: str, arguments: dict[str, str] | None
    ) -> GetPromptResult:
        arguments = arguments or {}

        if name == "explore_source":
            return _build_explore_source(registry, arguments)
        elif name == "deep_table_analysis":
            return _build_deep_table_analysis(registry, arguments)

        return GetPromptResult(
            description="Unknown prompt",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(type="text", text=f"Unknown prompt: {name}"),
                )
            ],
        )


def _build_explore_source(
    registry: SourceRegistry, arguments: dict[str, str]
) -> GetPromptResult:
    source_id = arguments.get("source_id", "")

    try:
        source = registry.get_source(source_id)
        context = source.get_context_description()
        tables = source.get_tables()
        table_names = [t.name for t in tables]
    except KeyError:
        return GetPromptResult(
            description="Source not found",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"Source '{source_id}' not found. Use list_sources to see available sources.",
                    ),
                )
            ],
        )

    prompt_text = f"""\
I want to explore a data source step by step. Here is the source information:

{context}

Please help me explore this data source by following these steps:

1. **Schema Overview**: Summarize the tables, their purposes, and approximate sizes.
   Use `get_source_schema("{source_id}")` to see the full schema.

2. **Table Profiling**: For the most interesting tables, run `profile_table("{source_id}", "<table>")` \
to understand data distributions and quality.

3. **Relationships**: Use `find_relationships("{source_id}")` to discover how tables connect. \
Then use `suggest_joins("{source_id}", ["<table1>", "<table2>"])` for common join patterns.

4. **Sample Data**: Run `get_table_sample("{source_id}", "<table>")` on 2-3 key tables \
to understand actual data values.

5. **Initial Questions**: Based on what you've learned, suggest 3-5 analytical questions \
that would be interesting to explore with this data.

Tables available: {', '.join(table_names)}

Start with step 1 and proceed through each step."""

    return GetPromptResult(
        description=f"Guided exploration of {source_id}",
        messages=[
            PromptMessage(
                role="user",
                content=TextContent(type="text", text=prompt_text),
            )
        ],
    )


def _build_deep_table_analysis(
    registry: SourceRegistry, arguments: dict[str, str]
) -> GetPromptResult:
    source_id = arguments.get("source_id", "")
    table_name = arguments.get("table_name", "")

    try:
        source = registry.get_source(source_id)
        tables = source.get_tables()
        table_info = None
        for t in tables:
            if t.name == table_name:
                table_info = t
                break
    except KeyError:
        return GetPromptResult(
            description="Source not found",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"Source '{source_id}' not found.",
                    ),
                )
            ],
        )

    if table_info is None:
        return GetPromptResult(
            description="Table not found",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"Table '{table_name}' not found in source '{source_id}'.",
                    ),
                )
            ],
        )

    columns_desc = "\n".join(
        f"  - {c.name}: {c.dtype} ({'NULL' if c.nullable else 'NOT NULL'})"
        for c in table_info.columns
    )
    row_count = f"{table_info.row_count:,}" if table_info.row_count else "unknown"

    prompt_text = f"""\
Perform an in-depth analysis of the table `{table_name}` from source `{source_id}`.

**Table Info:**
- Row count: {row_count}
- Primary keys: {', '.join(table_info.primary_keys) or 'none'}
- Columns:
{columns_desc}

Please analyze this table through these lenses:

1. **Structure Analysis**: Profile the table using `profile_table("{source_id}", "{table_name}")`. \
Examine column types, nullability, and completeness.

2. **Data Quality**: Check for:
   - Null rates across columns (which columns have missing data?)
   - Distinct value counts (which columns are high/low cardinality?)
   - Any columns that might need attention

3. **Distribution Patterns**: For the most important columns, use \
`profile_column("{source_id}", "{table_name}", "<column>")` to understand value distributions. \
Focus on key business columns.

4. **Relationships**: Use `find_relationships("{source_id}")` filtered to this table. \
How does it connect to other tables?

5. **Sample Analysis**: Use `get_table_sample("{source_id}", "{table_name}", 10)` \
and run a few analytical queries to uncover patterns:
   - Value distributions for categorical columns
   - Ranges and averages for numeric columns
   - Date ranges for temporal columns

6. **Insights & Recommendations**: Based on your analysis, provide:
   - Key findings about the data
   - Data quality concerns
   - Suggested analyses or questions to ask

Start the analysis now."""

    return GetPromptResult(
        description=f"Deep analysis of {table_name}",
        messages=[
            PromptMessage(
                role="user",
                content=TextContent(type="text", text=prompt_text),
            )
        ],
    )
