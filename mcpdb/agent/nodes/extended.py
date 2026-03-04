"""Extended mode nodes — checkpoint, revise, reflect."""

from __future__ import annotations

import logging
from typing import Any

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.llm.provider import LLMProvider, Message

logger = logging.getLogger("mcpdb.agent.extended")


# --- Checkpoint Node ---

CHECKPOINT_PROMPT = """\
Review the progress so far on this analysis.

USER QUESTION: {question}

COMPLETED STEPS:
{completed}

REMAINING STEPS:
{remaining}

Should we:
1. Continue with the remaining steps as planned
2. Revise the remaining steps based on what we've learned
3. Stop here — we have enough information

Respond with JSON:
{{"action": "continue|revise|done", "reason": "...", "revision_notes": "..." }}
"""


async def checkpoint(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
    step_interval: int = 3,
) -> AgentState:
    """Checkpoint node — review progress every N steps.

    Returns the state with checkpoint_action set to continue/revise/done.
    """
    plan = state.get("plan", {})
    idx = plan.get("current_step_index", 0)

    # Only checkpoint every N steps
    if idx == 0 or idx % step_interval != 0:
        state["checkpoint_action"] = "continue"
        return state

    callbacks.emit("checkpoint/start", step_index=idx)

    steps = plan.get("steps", [])
    completed = "\n".join(
        f"Step {s.get('step_number', i+1)}: {s.get('description', 'N/A')} — {s.get('status', 'unknown')}"
        for i, s in enumerate(steps[:idx])
    )
    remaining = "\n".join(
        f"Step {s.get('step_number', i+idx+1)}: {s.get('description', 'N/A')}"
        for i, s in enumerate(steps[idx:])
    )

    prompt = CHECKPOINT_PROMPT.format(
        question=state["question"],
        completed=completed or "None",
        remaining=remaining or "None",
    )

    try:
        result, usage = await llm.generate_json(
            [Message(role="user", content=prompt)],
            system="You are an analysis progress reviewer. Respond with JSON only.",
            max_tokens=512,
        )

        action = result.get("action", "continue")
        if action not in ("continue", "revise", "done"):
            action = "continue"

        state["checkpoint_action"] = action
        state["checkpoint_results"] = state.get("checkpoint_results", []) + [{
            "step_index": idx,
            "action": action,
            "reason": result.get("reason", ""),
        }]

        callbacks.emit("checkpoint/complete", action=action, reason=result.get("reason", ""))

    except Exception as e:
        logger.warning("Checkpoint failed: %s", e)
        state["checkpoint_action"] = "continue"

    return state


# --- Revise Node ---

REVISE_PROMPT = """\
Revise the remaining execution steps based on progress so far.

USER QUESTION: {question}

COMPLETED RESULTS:
{results}

REVISION NOTES: {notes}

REMAINING STEPS TO REVISE:
{remaining}

DATA SOURCES:
{source_context}

Create revised steps. Respond with JSON:
{{"steps": [{{\"step_number\": 1, \"action\": \"sql\", \"source_id\": \"...\", \"description\": \"...\", \"code\": \"...\"}}]}}
"""


async def revise_plan(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> AgentState:
    """Revise the remaining steps in the plan based on checkpoint feedback."""
    callbacks.emit("revise/start")

    plan = state.get("plan", {})
    steps = plan.get("steps", [])
    idx = plan.get("current_step_index", 0)

    results_text = "\n".join(
        f"Step {e.get('step_number', '?')}: {e.get('status', '?')} — {e.get('result_preview', '')}"
        for e in state.get("execution_log", [])
    )

    checkpoints = state.get("checkpoint_results", [])
    notes = checkpoints[-1].get("reason", "") if checkpoints else ""

    remaining = "\n".join(
        f"Step {s.get('step_number', i+idx+1)}: {s.get('description', '')}"
        for i, s in enumerate(steps[idx:])
    )

    prompt = REVISE_PROMPT.format(
        question=state["question"],
        results=results_text or "No results yet",
        notes=notes,
        remaining=remaining or "No remaining steps",
        source_context=state.get("source_context", ""),
    )

    try:
        result, usage = await llm.generate_json(
            [Message(role="user", content=prompt)],
            system="You are a data analysis planner. Respond with JSON only.",
            max_tokens=2048,
        )

        new_steps = result.get("steps", [])
        for step in new_steps:
            step.setdefault("status", "pending")
            step.setdefault("attempts", 0)

        # Replace remaining steps with revised ones
        plan["steps"] = steps[:idx] + new_steps
        plan["current_step_index"] = idx

        callbacks.emit("revise/ready", new_step_count=len(new_steps))

    except Exception as e:
        logger.warning("Revise failed: %s", e)
        callbacks.emit("revise/error", error=str(e))

    return state


# --- Reflect Node ---

REFLECT_PROMPT = """\
Reflect on the analysis you've completed.

USER QUESTION: {question}

EXECUTION LOG:
{results}

What patterns, insights, or unexpected findings emerged?
What were the limitations of this analysis?
Were there any data quality issues?

Respond in 2-3 concise paragraphs.
"""


async def reflect(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> AgentState:
    """Reflect on the completed analysis for richer synthesis."""
    callbacks.emit("reflect/start")

    results_text = "\n".join(
        f"Step {e.get('step_number', '?')} ({e.get('action', '?')}): "
        f"{e.get('status', '?')} — {e.get('result_preview', '')}"
        for e in state.get("execution_log", [])
    )

    prompt = REFLECT_PROMPT.format(
        question=state["question"],
        results=results_text or "No execution results.",
    )

    try:
        text, usage = await llm.generate(
            [Message(role="user", content=prompt)],
            system="You are a thoughtful data analyst. Provide insightful reflection.",
            max_tokens=1024,
        )
        state["reflection"] = text
        callbacks.emit("reflect/ready")

    except Exception as e:
        logger.warning("Reflection failed: %s", e)
        state["reflection"] = None

    return state
