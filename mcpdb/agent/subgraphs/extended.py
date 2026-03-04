"""Extended mode subgraph — plan → (execute ⟷ debug ⟷ checkpoint) → reflect → synthesize."""

from __future__ import annotations

import logging

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.nodes.common import make_plan, execute_step, debug_step, synthesize
from mcpdb.agent.nodes.extended import checkpoint, revise_plan, reflect
from mcpdb.agent.nodes.validators import validate_result, replan
from mcpdb.llm.provider import LLMProvider
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.agent.extended")

# Extended mode synthesize prompt includes reflection
EXTENDED_SYNTHESIZE_SYSTEM = (
    "You are a data analyst providing a comprehensive analysis. "
    "Include key findings, methodology notes, and any caveats."
)


async def run_extended(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
    registry: SourceRegistry,
    checkpoint_interval: int = 3,
) -> AgentState:
    """Execute the Extended mode subgraph.

    Flow: plan → (execute ⟷ debug ⟷ checkpoint/revise)* → reflect → validate → synthesize
    """
    callbacks.emit("extended/start")

    # 1. Plan
    state = await make_plan(state, llm, callbacks, registry)

    plan = state.get("plan")
    if not plan or not plan.get("steps"):
        state["response"] = "Could not create an execution plan."
        callbacks.emit("extended/complete", steps_executed=0)
        return state

    # 2. Execute with checkpoints
    state = await _execute_with_checkpoints(
        state, llm, callbacks, registry, checkpoint_interval,
    )

    # 3. Reflect on the analysis
    state = await reflect(state, llm, callbacks)

    # 4. Validate
    state = await validate_result(state, llm, callbacks)

    if state.get("validation_result") == "inadequate":
        state = await replan(state, llm, callbacks)
        new_plan = state.get("plan")
        if new_plan and new_plan.get("steps"):
            state = await _execute_with_checkpoints(
                state, llm, callbacks, registry, checkpoint_interval,
            )

    # 5. Synthesize (inject reflection into the synthesis prompt)
    if state.get("reflection"):
        # Augment source context with reflection for richer synthesis
        state["_reflection_context"] = state["reflection"]
    state = await synthesize(state, llm, callbacks)

    steps_executed = len(state.get("execution_log", []))
    callbacks.emit("extended/complete", steps_executed=steps_executed)
    return state


async def _execute_with_checkpoints(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
    registry: SourceRegistry,
    checkpoint_interval: int = 3,
) -> AgentState:
    """Execute steps with periodic checkpoints."""
    plan = state.get("plan", {})
    steps = plan.get("steps", [])
    max_iterations = len(steps) * (state.get("max_retries", 3) + 1)

    for _ in range(max_iterations):
        idx = plan.get("current_step_index", 0)
        if idx >= len(steps):
            break

        # Checkpoint before execution
        state = await checkpoint(state, llm, callbacks, step_interval=checkpoint_interval)

        action = state.get("checkpoint_action", "continue")
        if action == "done":
            logger.info("Checkpoint decided to stop at step %d", idx)
            break
        elif action == "revise":
            state = await revise_plan(state, llm, callbacks)
            steps = plan.get("steps", [])
            continue

        # Execute the step
        state = await execute_step(state, callbacks, registry)

        # Debug if needed
        if state.get("current_error"):
            state = await debug_step(state, llm, callbacks)

    return state
