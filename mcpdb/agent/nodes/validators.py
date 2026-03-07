"""Result validation and replan nodes."""

from __future__ import annotations

import logging
from typing import Any

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.llm.provider import LLMProvider, Message

logger = logging.getLogger("mcpdb.agent.validators")

VALIDATE_PROMPT = """\
Did the execution results adequately answer the user's question?

USER QUESTION: {question}

EXECUTION RESULTS:
{results}

If the results answer the question, respond: {{"result": "adequate"}}
If not, respond: {{"result": "inadequate", "reason": "What's missing"}}
"""


async def validate_result(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> AgentState:
    """Check if execution results answer the question."""
    # Skip validation if we've already replanned (prevent loops)
    if state.get("replan_count", 0) >= 1:
        state["validation_result"] = "adequate"
        return state

    callbacks.emit("validate/start")

    results_text = "\n".join(
        f"Step {e.get('step_number', '?')}: {e.get('status', '?')} — {e.get('result_summary', e.get('error', ''))}"
        for e in state.get("execution_log", [])
    )

    prompt = VALIDATE_PROMPT.format(
        question=state["question"],
        results=results_text or "No results",
    )

    try:
        result, usage = await llm.generate_json(
            [Message(role="user", content=prompt)],
            system="You are a result validator. Respond with JSON only.",
        )

        validation = result.get("result", "adequate")
        state["validation_result"] = validation
        if validation == "inadequate":
            state["validation_reason"] = result.get("reason", "")
            callbacks.emit("validate/inadequate", reason=state["validation_reason"])
        else:
            callbacks.emit("validate/adequate")

    except Exception as e:
        logger.warning("Validation failed, treating as adequate: %s", e)
        state["validation_result"] = "adequate"

    return state


REPLAN_PROMPT = """\
The previous execution did not adequately answer the question. Create a corrected plan.

USER QUESTION: {question}

PREVIOUS RESULTS:
{results}

REASON FOR REPLAN: {reason}

DATA SOURCES:
{source_context}

Create a corrected execution plan. Respond with JSON:
{{"analysis": "...", "approach": "...", "steps": [{{"step_number": 1, "action": "sql", "source_id": "...", "description": "...", "code": "..."}}]}}
"""


async def replan(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> AgentState:
    """Create a corrected plan based on validation feedback."""
    callbacks.emit("replan/start")

    results_text = "\n".join(
        f"Step {e.get('step_number', '?')}: {e.get('status', '?')} — {e.get('result_summary', e.get('error', ''))}"
        for e in state.get("execution_log", [])
    )

    prompt = REPLAN_PROMPT.format(
        question=state["question"],
        results=results_text,
        reason=state.get("validation_reason", "Unclear"),
        source_context=state.get("source_context", ""),
    )

    try:
        result, usage = await llm.generate_json(
            [Message(role="user", content=prompt)],
            system="You are a data analysis planner. Respond with JSON only.",
        )

        steps = result.get("steps", [])
        for step in steps:
            step.setdefault("status", "pending")
            step.setdefault("attempts", 0)

        state["plan"] = {
            "analysis": result.get("analysis", ""),
            "approach": result.get("approach", ""),
            "current_step_index": 0,
            "steps": steps,
        }
        state["replan_count"] = state.get("replan_count", 0) + 1
        state["current_error"] = None
        state["validation_result"] = None

        callbacks.emit("replan/ready", step_count=len(steps))

    except Exception as e:
        logger.warning("Replan failed: %s", e)
        state["validation_result"] = "adequate"  # Give up replanning

    return state
