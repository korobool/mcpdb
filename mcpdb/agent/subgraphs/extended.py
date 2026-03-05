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

    # 1. Plan (extended mode gets more steps)
    state = await make_plan(state, llm, callbacks, registry, query_mode="extended")

    plan = state.get("plan")
    if not plan or not plan.get("steps"):
        # Last resort: synthesize from context
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
    max_revisions: int = 2,
) -> AgentState:
    """Execute steps with periodic checkpoints."""
    plan = state.get("plan", {})
    steps = plan.get("steps", [])
    max_iterations = len(steps) * (state.get("max_retries", 3) + 1)
    revision_count = 0
    skip_next_checkpoint = False

    for _ in range(max_iterations):
        idx = plan.get("current_step_index", 0)
        if idx >= len(steps):
            break

        # Checkpoint before execution (skip after a revise to let revised steps run)
        if skip_next_checkpoint:
            skip_next_checkpoint = False
            state["checkpoint_action"] = "continue"
        else:
            state = await checkpoint(state, llm, callbacks, step_interval=checkpoint_interval)

        action = state.get("checkpoint_action", "continue")
        if action == "done":
            logger.info("Checkpoint decided to stop at step %d", idx)
            break
        elif action == "revise":
            if revision_count >= max_revisions:
                logger.info("Max revisions (%d) reached, continuing as-is", max_revisions)
            else:
                revision_count += 1
                state = await revise_plan(state, llm, callbacks)
                steps = plan.get("steps", [])
                skip_next_checkpoint = True
                continue

        # Execute the step
        state = await execute_step(state, callbacks, registry)

        # Debug if needed
        if state.get("current_error"):
            state = await debug_step(state, llm, callbacks)

    return state
