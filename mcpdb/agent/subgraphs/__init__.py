"""Agent mode subgraphs."""

from __future__ import annotations

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.llm.provider import LLMProvider
from mcpdb.sources.registry import SourceRegistry


async def dispatch_base_mode(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
    registry: SourceRegistry,
) -> AgentState:
    """Dispatch to the appropriate base mode runner based on state['query_mode'].

    Used by metamodes (sequential, deep) to run individual sub-questions
    through the correct base mode after classification.

    Handles quick → simple escalation automatically.
    Falls back to simple for unrecognized modes.
    """
    # Lazy imports to avoid circular dependencies
    from mcpdb.agent.subgraphs.quick import run_quick
    from mcpdb.agent.subgraphs.simple import run_simple
    from mcpdb.agent.subgraphs.extended import run_extended
    from mcpdb.agent.subgraphs.optimization import run_optimization

    mode = state.get("query_mode", "simple")

    if mode == "quick":
        state = await run_quick(state, llm, callbacks)
        # Handle escalation: quick → simple (same logic as graph.py)
        if state.get("validation_result") == "needs_data":
            state["query_mode"] = "simple"
            state = await run_simple(state, llm, callbacks, registry)

    elif mode == "optimization_required":
        state = await run_optimization(state, llm, callbacks, registry)

    elif mode == "extended":
        state = await run_extended(state, llm, callbacks, registry)

    else:
        # Default: simple
        if mode != "simple":
            state["query_mode"] = "simple"
        state = await run_simple(state, llm, callbacks, registry)

    return state
