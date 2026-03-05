"""Orchestrator graph — classify → route to subgraph → response."""

from __future__ import annotations

import logging
import time
from typing import Any

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.nodes.classify import classify
from mcpdb.agent.nodes.common import execute_step, synthesize
from mcpdb.agent.subgraphs.quick import run_quick
from mcpdb.agent.subgraphs.simple import run_simple
from mcpdb.agent.subgraphs.optimization import run_optimization
from mcpdb.agent.subgraphs.extended import run_extended
from mcpdb.agent.subgraphs.deep import run_deep
from mcpdb.experience.cache import ExperienceCache
from mcpdb.experience.fingerprint import (
    fingerprint_source, fingerprint_schema, intent_hash, semantic_hash,
)
from mcpdb.experience.records import CodeStep, StagedRecord, SuccessRecord
from mcpdb.experience.staging import StagingStore
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
    force_rethink: bool = False,
    staging_store: StagingStore | None = None,
) -> AgentState:
    """Run the full agent pipeline for a question.

    Classify → route to subgraph → return final state.
    Checks experience cache before running and stores results after success.

    Cache semantics: we cache the *code/plan*, not the response. On cache hit
    with executable steps, we re-execute them against live data and re-synthesize.
    Only quick-mode responses (no executable steps) are returned verbatim.

    If force_rethink is True, skip the cache entirely, run the full pipeline,
    and replace any existing cached entry with the new result.
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
    if experience_cache is not None and not force_rethink:
        for meta in registry.list_sources():
            cached = experience_cache.lookup(question, meta)
            if cached is not None:
                result = await _replay_cached(
                    cached, state, llm, callbacks, registry,
                )
                if result is not None:
                    return result

    # If rethinking, invalidate old cache entry so the new run replaces it
    if force_rethink and experience_cache is not None:
        for meta in registry.list_sources():
            experience_cache.invalidate(question, meta)
        callbacks.emit("experience/rethink", question=question)

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

    # Stage results for async quality evaluation (or auto-promote quick mode)
    if _is_cacheable(state):
        mode = state.get("query_mode", "unknown")
        executable = [
            e for e in state.get("execution_log", [])
            if e.get("action", e.get("action_type", "")) in ("sql", "python", "schema", "sample")
        ]
        is_quick = mode == "quick" and not executable

        if is_quick and experience_cache is not None:
            # Quick mode with no executable steps: auto-promote (deterministic)
            _store_experience(experience_cache, state, registry)
        elif staging_store is not None:
            # Stage for async quality evaluation
            _stage_experience(staging_store, state, registry)
        elif experience_cache is not None:
            # Fallback: no staging store, write directly (legacy path)
            _store_experience(experience_cache, state, registry)

    callbacks.emit("agent/complete", mode=mode, has_response=bool(state.get("response")))
    return state


async def _replay_cached(
    cached: SuccessRecord,
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
    registry: SourceRegistry,
) -> AgentState | None:
    """Replay a cached experience — re-execute code, re-synthesize from fresh results.

    Quick-mode responses (no executable steps) are returned directly since they
    are derived from the schema, which is already validated by the cache.
    Returns None if replay fails (caller should fall through to full pipeline).
    """
    executable_steps = [
        s for s in cached.steps
        if s.action_type in ("sql", "python", "schema", "sample")
    ]

    # Quick mode: no executable steps → return cached response directly.
    # Schema drift was already checked by the cache, so the response is valid.
    if not executable_steps:
        logger.info("Cache hit (quick, no steps): %s", cached.question[:60])
        callbacks.emit("experience/cache_hit", question=state["question"])
        state["cache_hit"] = True
        state["query_mode"] = cached.query_mode
        state["response"] = cached.response
        callbacks.emit("agent/complete", mode=cached.query_mode, has_response=True)
        return state

    # Has executable steps → replay the code against live data
    logger.info("Cache hit (replay %d steps): %s", len(executable_steps), cached.question[:60])
    callbacks.emit("experience/cache_hit", question=state["question"], replaying=True)

    state["cache_hit"] = True
    state["query_mode"] = cached.query_mode

    # Build a plan from cached steps so execute_step() can process them
    plan_steps = []
    for i, cs in enumerate(executable_steps):
        plan_steps.append({
            "step_number": i + 1,
            "action": cs.action_type,
            "code": cs.code,
            "source_id": state["active_source_ids"][0] if state["active_source_ids"] else "",
            "description": f"Cached {cs.action_type} step",
            "status": "pending",
            "attempts": 0,
        })

    state["plan"] = {
        "analysis": cached.question,
        "approach": "cached_replay",
        "current_step_index": 0,
        "steps": plan_steps,
    }

    # Execute each step against live data
    had_error = False
    for _ in range(len(plan_steps)):
        idx = state["plan"]["current_step_index"]
        if idx >= len(plan_steps):
            break
        state = await execute_step(state, callbacks, registry)
        if state.get("current_error"):
            # Cached code failed on current data — fall through to full pipeline
            logger.warning("Cached step %d failed, falling through to full pipeline", idx + 1)
            had_error = True
            break

    if had_error:
        # Reset state so the full pipeline starts fresh
        state["plan"] = None
        state["execution_log"] = []
        state["artifacts"] = []
        state["current_error"] = None
        state["cache_hit"] = False
        state["response"] = None
        return None

    # Re-synthesize from fresh execution results
    state = await synthesize(state, llm, callbacks)

    callbacks.emit("agent/complete", mode=cached.query_mode, has_response=bool(state.get("response")))
    return state


def _is_cacheable(state: AgentState) -> bool:
    """Quality gate — only cache results that are good enough to reuse.

    Rejects:
    - Empty or very short responses (likely failures)
    - Runs where validation marked results as inadequate
    - Runs where most steps failed
    - Error responses
    """
    response = state.get("response", "")
    if not response or len(response.strip()) < 20:
        logger.debug("Not caching: response too short")
        return False

    # Don't cache if validation said results were inadequate
    if state.get("validation_result") == "inadequate":
        logger.debug("Not caching: validation marked inadequate")
        return False

    # Don't cache error-like responses
    lower = response.lower()
    if any(phrase in lower for phrase in [
        "could not determine", "could not calculate", "unable to",
        "no data available", "failed to", "error:",
    ]):
        logger.debug("Not caching: response looks like an error")
        return False

    # Don't cache if majority of execution steps failed
    exec_log = state.get("execution_log", [])
    if exec_log:
        failed = sum(1 for e in exec_log if e.get("status") == "error")
        if failed > len(exec_log) / 2:
            logger.debug("Not caching: %d/%d steps failed", failed, len(exec_log))
            return False

    return True


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

    steps = _build_code_steps(state)

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


def _stage_experience(
    staging: StagingStore,
    state: AgentState,
    registry: SourceRegistry,
) -> None:
    """Stage a successful agent run for async quality evaluation."""
    question = state.get("question", "")
    response = state.get("response", "")
    mode = state.get("query_mode", "unknown")

    if not question or not response:
        return

    # Build CodeStep list from execution log
    steps = _build_code_steps(state)

    # Stage for each active source
    for meta in registry.list_sources():
        try:
            fp = fingerprint_source(meta)
            sh_schema = fingerprint_schema(meta)
            ih = intent_hash(question, fp)
            sh = semantic_hash(question, fp)

            record = StagedRecord(
                intent_hash=ih,
                question=question,
                source_fingerprint=fp,
                schema_hash=sh_schema,
                query_mode=mode,
                steps=steps,
                response=response,
                semantic_hash=sh,
            )
            staging.stage(record)
        except Exception as e:
            logger.warning("Failed to stage experience: %s", e)


def _build_code_steps(state: AgentState) -> list[CodeStep]:
    """Build CodeStep list from execution log."""
    steps = []
    for entry in state.get("execution_log", []):
        steps.append(CodeStep(
            action_type=entry.get("action", entry.get("action_type", "unknown")),
            code=entry.get("code", ""),
            result_preview=str(entry.get("result_preview", "")),
            time_ms=entry.get("time_ms", 0.0),
        ))
    return steps
