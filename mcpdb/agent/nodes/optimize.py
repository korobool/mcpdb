"""Optimize plan node — rewrite queries based on strategy choice."""

from __future__ import annotations

import logging
import re
from typing import Any

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.agent.optimize")


async def optimize_plan(
    state: AgentState,
    callbacks: CallbackManager,
    registry: SourceRegistry,
) -> AgentState:
    """Rewrite plan steps based on the chosen optimization strategy.

    Strategies:
    - SAMPLE: Rewrite SQL to use sampling (dialect-specific)
    - FULL: Keep original queries unchanged
    - CANCEL: Abort execution
    """
    strategy = state.get("strategy_choice", "FULL")
    callbacks.emit("optimize/start", strategy=strategy)

    if strategy == "CANCEL":
        state["response"] = "Query cancelled by user."
        state["optimization_state"] = "cancelled"
        callbacks.emit("optimize/cancelled")
        return state

    if strategy == "FULL":
        state["optimization_state"] = "full"
        callbacks.emit("optimize/full")
        return state

    if strategy == "SAMPLE":
        plan = state.get("plan", {})
        steps = plan.get("steps", [])

        for step in steps:
            if step.get("action") != "sql":
                continue

            source_id = step.get("source_id")
            code = step.get("code", "")

            # Try dialect-specific sampling first
            rewritten = _apply_sampling(code, source_id, registry)
            if rewritten != code:
                step["code"] = rewritten
                step["_original_code"] = code
                step["_sampling_applied"] = True

        state["optimization_state"] = "sampled"
        callbacks.emit("optimize/sampled", steps_modified=sum(
            1 for s in steps if s.get("_sampling_applied")
        ))

    return state


def _apply_sampling(
    code: str, source_id: str | None, registry: SourceRegistry,
    sample_percent: float = 5.0,
) -> str:
    """Rewrite SQL to add sampling using dialect-specific syntax."""
    try:
        source = _get_source(source_id, registry)
        if source is None:
            return _generic_limit_fallback(code)

        dialect = getattr(source, "dialect", None)
        if dialect is None:
            return _generic_limit_fallback(code)

        # Use dialect's add_sampling if available
        sampled = dialect.add_sampling(code, sample_percent)
        if sampled and sampled != code:
            return sampled

        return _generic_limit_fallback(code)

    except Exception as e:
        logger.debug("Sampling rewrite failed: %s", e)
        return _generic_limit_fallback(code)


def _generic_limit_fallback(code: str, limit: int = 10000) -> str:
    """Fallback: Add LIMIT if no LIMIT clause exists."""
    if re.search(r"\bLIMIT\s+\d+", code, re.IGNORECASE):
        return code  # Already has LIMIT
    return f"{code.rstrip().rstrip(';')} LIMIT {limit}"


def _get_source(source_id, registry):
    if source_id:
        try:
            return registry.get_source(source_id)
        except Exception:
            return None
    qs = registry.get_queryable_sources()
    return qs[0] if qs else None
