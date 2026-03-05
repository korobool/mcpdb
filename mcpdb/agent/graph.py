"""Orchestrator graph — classify → route to subgraph → response."""

from __future__ import annotations

import logging
from typing import Any

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.nodes.classify import classify
from mcpdb.agent.subgraphs.quick import run_quick
from mcpdb.agent.subgraphs.simple import run_simple
from mcpdb.agent.subgraphs.optimization import run_optimization
from mcpdb.agent.subgraphs.extended import run_extended
from mcpdb.agent.subgraphs.deep import run_deep
from mcpdb.experience.cache import ExperienceCache
from mcpdb.experience.records import CodeStep
from mcpdb.llm.provider import LLMProvider
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.agent.graph")


async def run_agent(
    question: str,
    registry: SourceRegistry,
    llm: LLMProvider,
    callbacks: CallbackManager | None = None,
    mode_override: str | None = None,
    experience_cache: ExperienceCache | None = None,
) -> AgentState:
    """Run the full agent pipeline for a question.

    Classify → route to subgraph → return final state.
    Checks experience cache before running and stores results after success.
    """
    if callbacks is None:
        callbacks = CallbackManager()

    # Build initial state
    source_context = registry.get_combined_context()
    active_ids = [m.source_id for m in registry.list_sources()]

    state: AgentState = {
        "question": question,
        "source_context": source_context,
        "active_source_ids": active_ids,
        "query_mode": None,
        "target_sources": [],
        "requires_cross_source": False,
        "key_entities": [],
        "response": None,
        "validation_result": None,
        "replan_count": 0,
        "artifacts": [],
        "execution_log": [],
        "max_retries": 3,
        "cache_hit": False,
    }

    # Check experience cache before doing any LLM work
    if experience_cache is not None:
        for meta in registry.list_sources():
            cached = experience_cache.lookup(question, meta)
            if cached is not None:
                logger.info("Experience cache hit for: %s", question[:60])
                callbacks.emit("experience/cache_hit", question=question)
                state["cache_hit"] = True
                state["cached_response"] = cached.response
                state["response"] = cached.response
                state["query_mode"] = cached.query_mode
                callbacks.emit("agent/complete", mode=cached.query_mode, has_response=True)
                return state

    # Apply mode override or classify
    if mode_override:
        state["query_mode"] = mode_override
        callbacks.emit("classify/override", mode=mode_override)
    else:
        state = await classify(state, llm, callbacks)

    mode = state.get("query_mode", "simple")

    # Route to subgraph
    if mode == "quick":
        state = await run_quick(state, llm, callbacks)

        # Handle escalation: quick → simple
        if state.get("validation_result") == "needs_data":
            logger.info("Quick mode escalated to simple")
            state["query_mode"] = "simple"
            state = await run_simple(state, llm, callbacks, registry)

    elif mode == "optimization_required":
        state = await run_optimization(state, llm, callbacks, registry)

    elif mode == "extended":
        state = await run_extended(state, llm, callbacks, registry)

    elif mode == "deep":
        state = await run_deep(state, llm, callbacks, registry)

    elif mode == "simple":
        state = await run_simple(state, llm, callbacks, registry)

    else:
        state["response"] = f"Unknown mode: {mode}"

    # Store successful results in experience cache
    if experience_cache is not None and state.get("response"):
        _store_experience(experience_cache, state, registry)

    callbacks.emit("agent/complete", mode=mode, has_response=bool(state.get("response")))
    return state


def _store_experience(
    cache: ExperienceCache,
    state: AgentState,
    registry: SourceRegistry,
) -> None:
    """Store a successful agent run in the experience cache."""
    question = state.get("question", "")
    response = state.get("response", "")
    mode = state.get("query_mode", "unknown")

    if not question or not response:
        return

    # Build CodeStep list from execution log
    steps = []
    for entry in state.get("execution_log", []):
        steps.append(CodeStep(
            action_type=entry.get("action_type", "unknown"),
            code=entry.get("code", ""),
            result_preview=str(entry.get("result_preview", "")),
            time_ms=entry.get("time_ms", 0.0),
        ))

    # Store for each active source
    for meta in registry.list_sources():
        try:
            cache.store(
                question=question,
                source_metadata=meta,
                query_mode=mode,
                steps=steps,
                response=response,
            )
        except Exception as e:
            logger.warning("Failed to store experience: %s", e)
