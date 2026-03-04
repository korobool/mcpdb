"""Execution control MCP tools — cancel_execution, add_context, submit_strategy."""

from __future__ import annotations

import logging
from typing import Any

from mcp.types import TextContent, Tool

logger = logging.getLogger("mcpdb.mcp.control")

_TOOLS = [
    Tool(
        name="cancel_execution",
        description="Cancel an in-progress agent execution.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID (optional, cancels current execution by default)",
                    "default": "default",
                },
            },
        },
    ),
    Tool(
        name="add_context",
        description=(
            "Add context or instructions to a running agent execution. "
            "The agent will incorporate this before the next step."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Additional context or instructions",
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID (optional, targets current execution by default)",
                    "default": "default",
                },
            },
            "required": ["text"],
        },
    ),
    Tool(
        name="submit_strategy",
        description=(
            "Submit a strategy choice for an expensive query that was paused by the cost gate. "
            "Strategies: SAMPLE (fast, approximate), FULL (slow, exact), CANCEL (abort)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "enum": ["SAMPLE", "FULL", "CANCEL"],
                    "description": "The optimization strategy to use",
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID",
                    "default": "default",
                },
            },
            "required": ["strategy"],
        },
    ),
]


# Session-level state for cancellation tokens and input queues
_session_state: dict[str, dict[str, Any]] = {}


def get_session_state(session_id: str = "default") -> dict[str, Any]:
    """Get or create session-level state."""
    if session_id not in _session_state:
        from mcpdb.agent.cancellation import CancellationToken
        from mcpdb.agent.user_input import UserInputQueue
        _session_state[session_id] = {
            "cancellation": CancellationToken(),
            "input_queue": UserInputQueue(),
        }
    return _session_state[session_id]


def reset_session_state(session_id: str = "default") -> None:
    """Reset session state (e.g., after execution completes)."""
    state = get_session_state(session_id)
    state["cancellation"].reset()
    state["input_queue"].clear()


def get_control_tools() -> list[Tool]:
    return list(_TOOLS)


def handle_control_tool(
    name: str, args: dict[str, Any],
) -> list[TextContent]:
    if name == "cancel_execution":
        return _cancel_execution(args)
    elif name == "add_context":
        return _add_context(args)
    elif name == "submit_strategy":
        return _submit_strategy(args)
    return [TextContent(type="text", text=f"Unknown control tool: {name}")]


def _cancel_execution(args: dict[str, Any]) -> list[TextContent]:
    session_id = args.get("session_id", "default")
    state = get_session_state(session_id)
    state["cancellation"].cancel()
    return [TextContent(type="text", text="Cancellation requested. The agent will stop at the next checkpoint.")]


def _add_context(args: dict[str, Any]) -> list[TextContent]:
    session_id = args.get("session_id", "default")
    text = args["text"]
    state = get_session_state(session_id)
    state["input_queue"].add(text)
    return [TextContent(type="text", text="Context added. The agent will incorporate it before the next step.")]


def _submit_strategy(args: dict[str, Any]) -> list[TextContent]:
    from mcpdb.agent.nodes.strategy_gate import consume_pending_strategy

    session_id = args.get("session_id", "default")
    strategy = args["strategy"]

    pending = consume_pending_strategy(session_id)
    if pending is None:
        return [TextContent(type="text", text="No pending strategy request found (may have expired).")]

    pending.state["strategy_choice"] = strategy
    pending.state["optimization_state"] = "strategy_received"
    pending.callbacks.emit("strategy_gate/received", strategy=strategy)

    if strategy == "CANCEL":
        pending.state["response"] = "Query cancelled by user."
        return [TextContent(type="text", text="Query cancelled.")]

    return [TextContent(
        type="text",
        text=f"Strategy '{strategy}' accepted. The agent will resume execution.",
    )]
