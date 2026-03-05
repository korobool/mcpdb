"""LLM-assisted analysis MCP tools — ask_question, suggest_followups."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp.types import TextContent, Tool

from mcpdb.experience.cache import ExperienceCache
from mcpdb.experience.store import ExperienceStore
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.mcp.analysis")

# Module-level singleton — shared across all MCP tool calls
_experience_store = ExperienceStore()
_experience_cache = ExperienceCache(store=_experience_store)

_TOOLS = [
    Tool(
        name="ask_question",
        description=(
            "Ask a natural language question about your data. "
            "The agent will classify, plan, execute queries, and synthesize a response."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Your question about the data",
                },
                "mode": {
                    "type": "string",
                    "enum": ["auto", "quick", "simple", "extended", "deep"],
                    "default": "auto",
                    "description": "Thinking mode override (auto = let classifier decide)",
                },
            },
            "required": ["question"],
        },
    ),
    Tool(
        name="suggest_followups",
        description=(
            "Suggest follow-up questions based on the data sources and recent analysis. "
            "Returns 3-5 context-aware questions to explore next."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "context": {
                    "type": "string",
                    "description": "Optional: recent question/answer context for better suggestions",
                },
            },
        },
    ),
]


def get_analysis_tools() -> list[Tool]:
    return list(_TOOLS)


def handle_analysis_tool(
    name: str, args: dict[str, Any], registry: SourceRegistry, llm: Any,
) -> list[TextContent]:
    if name == "ask_question":
        return _ask_question(registry, args, llm)
    elif name == "suggest_followups":
        return _suggest_followups(registry, args, llm)
    return [TextContent(type="text", text=f"Unknown analysis tool: {name}")]


def _ask_question(
    registry: SourceRegistry, args: dict[str, Any], llm: Any,
) -> list[TextContent]:
    from mcpdb.agent.graph import run_agent
    from mcpdb.agent.callbacks import CallbackManager

    question = args["question"]
    mode = args.get("mode", "auto")
    mode_override = None if mode == "auto" else mode

    callbacks = CallbackManager()

    # Run the agent synchronously (MCP tool handlers are sync in our dispatch)
    loop = asyncio.new_event_loop()
    try:
        state = loop.run_until_complete(
            run_agent(
                question=question,
                registry=registry,
                llm=llm,
                callbacks=callbacks,
                mode_override=mode_override,
                experience_cache=_experience_cache,
            )
        )
    finally:
        loop.close()

    response = state.get("response", "No response generated.")
    mode_used = state.get("query_mode", "unknown")

    # Build response with metadata
    parts = [response]
    if state.get("artifacts"):
        parts.append(f"\n[{len(state['artifacts'])} artifact(s) generated]")

    events = callbacks.get_events()
    event_summary = " → ".join(e.type for e in events)
    parts.append(f"\n\n_Mode: {mode_used} | Steps: {event_summary}_")

    return [TextContent(type="text", text="\n".join(parts))]


_FOLLOWUP_PROMPT = """\
You are a data analyst assistant. Given the database schema below and optional recent context, \
suggest 3-5 insightful follow-up questions that would help the user explore their data further.

Focus on:
- Trends and patterns (e.g., "How has X changed over time?")
- Comparisons and segments (e.g., "Which category has the highest Y?")
- Anomalies (e.g., "Are there any outliers in Z?")
- Relationships (e.g., "What is the correlation between A and B?")

Return ONLY a JSON array of strings, no other text. Example:
["Question 1?", "Question 2?", "Question 3?"]

## Schema
{schema}

## Recent Context
{context}
"""


def _suggest_followups(
    registry: SourceRegistry, args: dict[str, Any], llm: Any,
) -> list[TextContent]:
    from mcpdb.llm.provider import Message

    if llm is None:
        return [TextContent(type="text", text="LLM not configured. Cannot generate suggestions.")]

    sources = registry.list_sources()
    if not sources:
        return [TextContent(type="text", text="No data sources connected. Connect a source first.")]

    schema = registry.get_combined_context()
    context = args.get("context", "No recent context.")

    prompt = _FOLLOWUP_PROMPT.format(schema=schema, context=context)

    loop = asyncio.new_event_loop()
    try:
        result, _usage = loop.run_until_complete(
            llm.generate_json(
                [Message(role="user", content=prompt)],
                temperature=0.7,
            )
        )
    except Exception as e:
        logger.error("Failed to generate follow-ups: %s", e)
        return [TextContent(type="text", text=f"Failed to generate suggestions: {e}")]
    finally:
        loop.close()

    if isinstance(result, list):
        lines = ["## Suggested Follow-up Questions"]
        for i, q in enumerate(result, 1):
            lines.append(f"{i}. {q}")
        return [TextContent(type="text", text="\n".join(lines))]

    return [TextContent(type="text", text="Unexpected response format from LLM.")]
