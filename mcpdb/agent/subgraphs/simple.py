"""Simple mode subgraph — plan → execute ⟷ debug → validate → replan → synthesize."""

from __future__ import annotations

import logging

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.nodes.common import make_plan, execute_step, debug_step, synthesize
from mcpdb.agent.nodes.validators import validate_result, replan
from mcpdb.llm.provider import LLMProvider
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.agent.simple")


async def run_simple(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
    registry: SourceRegistry,
) -> AgentState:
    """Execute the Simple mode subgraph.

    Flow: plan → (execute ⟷ debug)* → validate → [replan → loop] → synthesize
    """
    callbacks.emit("simple/start")

    # 1. Plan (includes retry + fallback logic)
    state = await make_plan(state, llm, callbacks, registry, query_mode="simple")

    plan = state.get("plan")
    if not plan or not plan.get("steps"):
        # Last resort: synthesize an answer from source context alone
        logger.warning("No plan steps available, synthesizing from context")
        state["execution_log"] = [{
            "step_number": 0,
            "action": "context",
            "code": "",
            "status": "success",
            "result_preview": state.get("source_context", "No data available"),
            "time_ms": 0,
        }]
        state = await synthesize(state, llm, callbacks)
        callbacks.emit("simple/complete", steps_executed=0)
        return state

    # 2. Execute all steps (with debug retries)
    state = await _execute_all_steps(state, llm, callbacks, registry)

    # 3. Validate results
    state = await validate_result(state, llm, callbacks)

    # 4. If inadequate and haven't replanned yet, replan and re-execute
    if state.get("validation_result") == "inadequate":
        state = await replan(state, llm, callbacks)

        # Re-execute the new plan if replan succeeded
        new_plan = state.get("plan")
        if new_plan and new_plan.get("steps"):
            state = await _execute_all_steps(state, llm, callbacks, registry)

    # 5. Synthesize final answer
    state = await synthesize(state, llm, callbacks)

    steps_executed = len(state.get("execution_log", []))
    callbacks.emit("simple/complete", steps_executed=steps_executed)
    return state


async def _execute_all_steps(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
    registry: SourceRegistry,
) -> AgentState:
    """Execute all plan steps, retrying failed steps via debug node."""
    plan = state.get("plan", {})
    steps = plan.get("steps", [])
    max_iterations = len(steps) * (state.get("max_retries", 3) + 1)

    for _ in range(max_iterations):
        idx = plan.get("current_step_index", 0)
        if idx >= len(steps):
            break  # All steps done

        state = await execute_step(state, callbacks, registry)

        # If there's an error, try to debug/fix it
        if state.get("current_error"):
            state = await debug_step(state, llm, callbacks)
            # debug_step either fixes the code (sets status=pending, clears error)
            # or gives up (advances index, clears error)
            # Either way, loop continues
        # If no error, execute_step already advanced the index

    return state
