"""Optimization mode subgraph — plan → cost_check → strategy_gate → optimize → execute → synthesize."""

from __future__ import annotations

import logging

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.nodes.common import make_plan, execute_step, debug_step, synthesize
from mcpdb.agent.nodes.cost_check import cost_check
from mcpdb.agent.nodes.strategy_gate import strategy_gate
from mcpdb.agent.nodes.optimize import optimize_plan
from mcpdb.agent.nodes.validators import validate_result
from mcpdb.llm.provider import LLMProvider
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.agent.optimization")


async def run_optimization(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
    registry: SourceRegistry,
    session_id: str = "default",
) -> AgentState:
    """Execute the Optimization mode subgraph.

    Flow: plan → cost_check → [strategy_gate] → optimize_plan → execute → synthesize
    """
    callbacks.emit("optimization/start")

    # 1. Plan
    state = await make_plan(state, llm, callbacks, registry, query_mode="optimization_required")

    plan = state.get("plan")
    if not plan or not plan.get("steps"):
        state["response"] = "Could not create an execution plan."
        callbacks.emit("optimization/complete", steps_executed=0)
        return state

    # 2. Cost check
    state = await cost_check(state, llm, callbacks, registry)

    cost_decision = state.get("cost_analysis", {}).get("decision", "not_required")

    # 3. Strategy gate (if needed)
    if cost_decision != "not_required":
        state = await strategy_gate(state, callbacks, session_id)

        # If awaiting strategy, return immediately (will be resumed via submit_strategy)
        if state.get("optimization_state") == "awaiting_strategy":
            callbacks.emit("optimization/paused")
            return state

    # 4. Optimize plan based on strategy
    state = await optimize_plan(state, callbacks, registry)

    # If cancelled, return
    if state.get("optimization_state") == "cancelled":
        callbacks.emit("optimization/complete", steps_executed=0)
        return state

    # 5. Execute all steps
    state = await _execute_all_steps(state, llm, callbacks, registry)

    # 6. Synthesize
    state = await synthesize(state, llm, callbacks)

    steps_executed = len(state.get("execution_log", []))
    callbacks.emit("optimization/complete", steps_executed=steps_executed)
    return state


async def _execute_all_steps(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
    registry: SourceRegistry,
) -> AgentState:
    """Execute all plan steps with debug retries."""
    plan = state.get("plan", {})
    steps = plan.get("steps", [])
    max_iterations = len(steps) * (state.get("max_retries", 3) + 1)

    for _ in range(max_iterations):
        idx = plan.get("current_step_index", 0)
        if idx >= len(steps):
            break

        state = await execute_step(state, callbacks, registry)

        if state.get("current_error"):
            state = await debug_step(state, llm, callbacks)

    return state
