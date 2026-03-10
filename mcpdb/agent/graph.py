"""Orchestrator graph — classify → route to subgraph → response."""

from __future__ import annotations

import logging
import random
import time
from typing import Any

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.cancellation import CancellationToken
from mcpdb.agent.nodes.classify import classify
from mcpdb.agent.observer import AsyncReasoningObserver
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
from mcpdb.agent.tracking import TrackingLLMProvider
from mcpdb.llm.provider import LLMProvider
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.agent.graph")

_OFF_TOPIC_RESPONSES = [
    "I'd love to chat, but I only speak fluent SQL. Ask me something about your data!",
    "My talents are limited to crunching numbers and querying databases. Try me with a data question!",
    "I'm basically a data detective — great with tables, terrible at small talk. Got a data question?",
    "Interesting thought! But I'm a data assistant, not a philosopher. What would you like to know about your data?",
    "I tried to answer that, but my inner JOIN couldn't find a match. Ask me about your data instead!",
    "That's a bit outside my SELECT * FROM expertise. I'm here to help you explore your data!",
    "I'm flattered, but I'm a one-trick pony — and that trick is data analysis. Fire away!",
    "404: General knowledge not found. But I have 100% uptime on data questions!",
    "My WHERE clause doesn't cover that topic. I'm built to help you talk with your data!",
    "I appreciate the question, but my training data is... well, your actual data. What shall we explore?",
]


async def run_agent(
    question: str,
    registry: SourceRegistry,
    llm: LLMProvider,
    callbacks: CallbackManager | None = None,
    mode_override: str | None = None,
    experience_cache: ExperienceCache | None = None,
    force_rethink: bool = False,
    staging_store: StagingStore | None = None,
    no_cache: bool = False,
    cancellation_token: CancellationToken | None = None,
    enable_observer: bool = True,
    knowledge_manager: Any = None,
) -> AgentState:
    """Run the full agent pipeline for a question.

    Classify → route to subgraph → return final state.
    Checks experience cache before running and stores results after success.

    Cache semantics: we cache the *code/plan*, not the response. On cache hit
    with executable steps, we re-execute them against live data and re-synthesize.
    Only quick-mode responses (no executable steps) are returned verbatim.

    If force_rethink is True, skip the cache entirely, run the full pipeline,
    and replace any existing cached entry with the new result.

    If no_cache is True, skip cache lookup but still populate the cache on
    success. Unlike force_rethink, this does not invalidate existing entries.
    """
    if callbacks is None:
        callbacks = CallbackManager()

    # Wrap LLM for automatic token tracking
    tracking_llm = TrackingLLMProvider(llm, callbacks)
    llm = tracking_llm  # type: ignore[assignment]

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
        "cancellation_token": cancellation_token,
    }

    # Build anti-pattern context from experience data
    if experience_cache is not None:
        try:
            from mcpdb.experience.antipatterns import AntiPatternTracker
            tracker = AntiPatternTracker(store=experience_cache._store)
            for meta in registry.list_sources():
                ctx = tracker.get_anti_pattern_context(meta)
                if ctx:
                    state["experience_context"] = ctx
                    logger.info("Anti-pattern context injected: %d chars", len(ctx))
                    break
        except Exception as e:
            logger.debug("Failed to build anti-pattern context: %s", e)

    # Inject knowledge context from RAG
    if knowledge_manager is not None:
        try:
            knowledge_ctx = knowledge_manager.retrieve(
                question,
                injection_point="plan",
            )
            if knowledge_ctx:
                state["knowledge_context"] = knowledge_ctx
                logger.info("Knowledge context injected: %d chars", len(knowledge_ctx))
        except Exception as e:
            logger.debug("Failed to retrieve knowledge context: %s", e)

    # Check experience cache before doing any LLM work
    if experience_cache is not None and not force_rethink and not no_cache:
        for meta in registry.list_sources():
            cached = experience_cache.lookup(question, meta, mode_override=mode_override)
            if cached is not None:
                result = await _replay_cached(
                    cached, state, llm, callbacks, registry,
                )
                if result is not None:
                    result["llm_usage"] = {
                        "calls": tracking_llm.usage.calls,
                        "input_tokens": tracking_llm.usage.input_tokens,
                        "output_tokens": tracking_llm.usage.output_tokens,
                        "total_tokens": tracking_llm.usage.input_tokens + tracking_llm.usage.output_tokens,
                    }
                    return result

    # If rethinking, invalidate old cache entry so the new run replaces it
    if force_rethink and experience_cache is not None:
        for meta in registry.list_sources():
            experience_cache.invalidate(question, meta)
        callbacks.emit("experience/rethink", question=question)

    # Start observer for parallel monitoring
    observer: AsyncReasoningObserver | None = None
    if enable_observer:
        observer = AsyncReasoningObserver(callbacks, cancellation_token)

    # Apply mode override or classify
    if mode_override:
        state["query_mode"] = mode_override
        callbacks.emit("classify/override", mode=mode_override)
    else:
        state = await classify(state, llm, callbacks)

    mode = state.get("query_mode", "simple")

    # Start observer now that we know the mode
    if observer is not None:
        observer.start(question=question, mode=mode)

    # Route to subgraph
    if mode == "off_topic":
        state["response"] = random.choice(_OFF_TOPIC_RESPONSES)
        callbacks.emit("agent/complete", mode=mode, has_response=True)
        # Store usage and return early — no observer, no caching
        state["llm_usage"] = {
            "calls": tracking_llm.usage.calls,
            "input_tokens": tracking_llm.usage.input_tokens,
            "output_tokens": tracking_llm.usage.output_tokens,
            "total_tokens": tracking_llm.usage.input_tokens + tracking_llm.usage.output_tokens,
        }
        if observer is not None:
            observer.stop()
        return state

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

    # Record execution failures as anti-patterns
    if experience_cache is not None:
        try:
            from mcpdb.experience.antipatterns import AntiPatternTracker
            tracker = AntiPatternTracker(store=experience_cache._store)
            for entry in state.get("execution_log", []):
                if entry.get("status") == "error":
                    for meta in registry.list_sources():
                        tracker.record_failure(
                            question=question,
                            source_metadata=meta,
                            error_type="execution_error",
                            error_message=str(entry.get("error", "")),
                            failed_code=entry.get("code", ""),
                        )
        except Exception as e:
            logger.debug("Failed to record execution failures: %s", e)

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

    # Stop observer and collect report
    observer_report = None
    if observer is not None:
        observer_report = observer.stop()
        state["observer_report"] = observer_report.to_dict()
        if observer_report.had_anomalies:
            logger.info("Observer report:\n%s", observer_report.summary())
            callbacks.emit(
                "observer/report",
                anomaly_count=len(observer_report.anomalies),
                total_time=observer_report.total_time,
                summary=observer_report.summary(),
            )

    # Store accumulated token usage
    state["llm_usage"] = {
        "calls": tracking_llm.usage.calls,
        "input_tokens": tracking_llm.usage.input_tokens,
        "output_tokens": tracking_llm.usage.output_tokens,
        "total_tokens": tracking_llm.usage.input_tokens + tracking_llm.usage.output_tokens,
    }

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
    # Use cached plan metadata for richer descriptions when available
    cached_step_descs = (cached.plan_metadata.get("step_descriptions") or []) if cached.plan_metadata else []

    plan_steps = []
    for i, cs in enumerate(executable_steps):
        desc = f"Cached {cs.action_type} step"
        if i < len(cached_step_descs):
            desc = cached_step_descs[i].get("description", desc)

        plan_steps.append({
            "step_number": i + 1,
            "action": cs.action_type,
            "code": cs.code,
            "source_id": state["active_source_ids"][0] if state["active_source_ids"] else "",
            "description": desc,
            "status": "pending",
            "attempts": 0,
        })

    state["plan"] = {
        "analysis": cached.plan_metadata.get("analysis", cached.question) if cached.plan_metadata else cached.question,
        "approach": cached.plan_metadata.get("approach", "cached_replay") if cached.plan_metadata else "cached_replay",
        "current_step_index": 0,
        "steps": plan_steps,
    }

    # Execute each step against live data
    had_error = False
    try:
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
    except Exception as e:
        logger.warning("Unexpected error during cache replay: %s", e)
        had_error = True

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
    plan_meta = _extract_plan_metadata(state)

    # Store for each active source
    for meta in registry.list_sources():
        try:
            cache.store(
                question=question,
                source_metadata=meta,
                query_mode=mode,
                steps=steps,
                response=response,
                plan_metadata=plan_meta,
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
    plan_meta = _extract_plan_metadata(state)

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
                plan_metadata=plan_meta,
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
            result_preview=str(entry.get("result_summary", entry.get("result_preview", ""))),
            time_ms=entry.get("time_ms", 0.0),
        ))
    return steps


def _extract_plan_metadata(state: AgentState) -> dict[str, Any]:
    """Extract plan/blueprint metadata from state for caching."""
    pm: dict[str, Any] = {}

    # Standard plan metadata (simple, extended, optimization modes)
    plan = state.get("plan")
    if plan:
        pm["analysis"] = plan.get("analysis", "")
        pm["approach"] = plan.get("approach", "")
        pm["step_descriptions"] = [
            {
                "step_number": s.get("step_number", i + 1),
                "action": s.get("action", ""),
                "description": s.get("description", ""),
            }
            for i, s in enumerate(plan.get("steps", []))
        ]

    # Deep mode blueprint
    blueprint = state.get("blueprint")
    if blueprint:
        pm["blueprint"] = {
            "research_goal": blueprint.get("research_goal", ""),
            "investigations": [
                {
                    "id": inv.get("id"),
                    "question": inv.get("question", ""),
                    "approach": inv.get("approach", ""),
                    "priority": inv.get("priority", "medium"),
                }
                for inv in blueprint.get("investigations", [])
            ],
        }

    return pm
