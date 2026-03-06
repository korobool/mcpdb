"""LLM-assisted analysis MCP tools — ask_question, suggest_followups."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mcp.types import TextContent, Tool

from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.mcp.analysis")

# Human-readable labels for agent events (sent as MCP log notifications)
_EVENT_LABELS = {
    "classify/start": "Classifying question",
    "plan/start": "Planning analysis",
    "plan/retry": "Retrying plan",
    "plan/error": "Plan failed, using fallback",
    "debug/start": "Debugging failed step",
    "debug/fixed": "Fix applied",
    "debug/give_up": "Skipping failed step",
    "checkpoint/start": "Reviewing progress",
    "revise/start": "Revising plan",
    "reflect/start": "Reflecting on results",
    "validate/start": "Validating results",
    "validate/inadequate": "Results incomplete, replanning",
    "replan/start": "Creating corrected plan",
    "synthesize/start": "Synthesizing response",
    "experience/cache_hit": "Using cached result",
    "quick/start": "Answering from context",
    "quick/escalate": "Escalating to full analysis",
}


def _attach_progress_notifier(callbacks) -> None:
    """Attach a listener that forwards agent events as MCP log notifications."""
    try:
        from mcp.server.lowlevel.server import request_ctx
        ctx = request_ctx.get()
        session = ctx.session
    except (LookupError, AttributeError):
        return  # Not running inside an MCP request context

    step_count = 0

    def _on_event(event) -> None:
        nonlocal step_count
        etype = event.type
        data = event.data
        msg = None

        if etype == "classify/complete":
            msg = f"Mode: {data.get('mode', '?')}"
        elif etype == "plan/ready":
            step_count = data.get("step_count", 0)
            msg = f"Plan ready — {step_count} steps"
        elif etype == "step/start":
            step_num = data.get("step_number", "?")
            action = data.get("action", "")
            total = step_count or "?"
            msg = f"Step {step_num}/{total}: {action}"
        elif etype == "step/complete":
            step_num = data.get("step_number", "?")
            ms = data.get("time_ms", 0)
            msg = f"Step {step_num} done ({ms}ms)"
        elif etype == "step/error":
            step_num = data.get("step_number", "?")
            err = str(data.get("error", ""))[:80]
            msg = f"Step {step_num} error: {err}"
        elif etype == "replan/ready":
            step_count = data.get("step_count", 0)
            msg = f"New plan — {step_count} steps"
        elif etype == "revise/ready":
            msg = f"Revised — {data.get('new_step_count', 0)} steps remaining"
        elif etype in _EVENT_LABELS:
            msg = _EVENT_LABELS[etype]

        if msg is not None:
            try:
                session.send_log_message(level="info", data=msg, logger="mcpdb.progress")
            except Exception:
                pass  # Best-effort; don't break agent on notification failure

    callbacks.add_listener(_on_event)


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
                "rethink": {
                    "type": "boolean",
                    "default": False,
                    "description": "Force fresh analysis: bypass cache, re-plan from scratch, replace cached solution",
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


async def handle_analysis_tool(
    name: str, args: dict[str, Any], registry: SourceRegistry, llm: Any,
    experience_service: Any = None,
) -> list[TextContent]:
    if name == "ask_question":
        return await _ask_question(registry, args, llm, experience_service=experience_service)
    elif name == "suggest_followups":
        return await _suggest_followups(registry, args, llm)
    return [TextContent(type="text", text=f"Unknown analysis tool: {name}")]


async def _ask_question(
    registry: SourceRegistry, args: dict[str, Any], llm: Any,
    experience_service: Any = None,
) -> list[TextContent]:
    from mcpdb.agent.graph import run_agent
    from mcpdb.agent.callbacks import CallbackManager

    question = args["question"]
    mode = args.get("mode", "auto")
    mode_override = None if mode == "auto" else mode
    force_rethink = args.get("rethink", False)

    callbacks = CallbackManager()

    # Forward agent events as MCP log notifications for real-time progress
    _attach_progress_notifier(callbacks)

    # Resolve experience components from service or create inline fallback
    if experience_service is not None:
        experience_cache = experience_service.cache
        staging_store = experience_service.staging
    else:
        from mcpdb.experience.cache import ExperienceCache
        from mcpdb.experience.staging import StagingStore
        from mcpdb.experience.store import ExperienceStore
        _store = ExperienceStore()
        experience_cache = ExperienceCache(store=_store)
        staging_store = StagingStore()

    state = await run_agent(
        question=question,
        registry=registry,
        llm=llm,
        callbacks=callbacks,
        mode_override=mode_override,
        experience_cache=experience_cache,
        force_rethink=force_rethink,
        staging_store=staging_store,
    )

    response = state.get("response", "No response generated.")
    mode_used = state.get("query_mode", "unknown")

    # Truncate large table artifacts (>200 rows)
    artifacts = []
    for a in state.get("artifacts", []):
        if a.get("type") == "table":
            rows = a.get("data", {}).get("rows", [])
            if len(rows) > 200:
                a = {**a, "data": {**a["data"], "rows": rows[:200], "truncated": True}}
        artifacts.append(a)

    events = callbacks.get_events()

    # Best-effort inline followups
    followups = await _generate_followups_inline(registry, llm, question)

    result_json = {
        "response": response,
        "mode": mode_used,
        "artifacts": artifacts,
        "execution_log": state.get("execution_log", []),
        "followups": followups,
        "event_summary": " → ".join(e.type for e in events),
    }
    return [TextContent(type="text", text=json.dumps(result_json))]


async def _generate_followups_inline(
    registry: SourceRegistry, llm: Any, question: str,
) -> list[str]:
    """Best-effort follow-up generation, reusing the suggest_followups prompt."""
    if llm is None:
        return []
    sources = registry.list_sources()
    if not sources:
        return []

    from mcpdb.llm.provider import Message

    schema = registry.get_combined_context()
    prompt = _FOLLOWUP_PROMPT.format(schema=schema, context=question)
    try:
        result, _usage = await asyncio.wait_for(
            llm.generate_json(
                [Message(role="user", content=prompt)],
                temperature=0.7,
            ),
            timeout=15,
        )
        if isinstance(result, list):
            return [str(q) for q in result[:5]]
    except Exception:
        logger.debug("Inline followup generation failed", exc_info=True)
    return []


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


async def _suggest_followups(
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

    try:
        result, _usage = await llm.generate_json(
            [Message(role="user", content=prompt)],
            temperature=0.7,
        )
    except Exception as e:
        logger.error("Failed to generate follow-ups: %s", e)
        return [TextContent(type="text", text=f"Failed to generate suggestions: {e}")]

    if isinstance(result, list):
        lines = ["## Suggested Follow-up Questions"]
        for i, q in enumerate(result, 1):
            lines.append(f"{i}. {q}")
        return [TextContent(type="text", text="\n".join(lines))]

    return [TextContent(type="text", text="Unexpected response format from LLM.")]
