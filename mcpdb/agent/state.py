"""Agent state definition — shared across all modes."""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class AgentState(TypedDict, total=False):
    """Shared state for all subgraphs.

    Fields are grouped by which mode(s) use them.
    Using total=False so modes only set fields they need.
    """

    # --- Input (set before graph invocation) ---
    question: str
    source_context: str
    active_source_ids: list[str]

    # --- Classification (set by classify node) ---
    query_mode: Literal["quick", "simple", "extended", "optimization_required", "deep", "sequential", "off_topic"] | None
    target_sources: list[str]
    requires_cross_source: bool
    key_entities: list[str]

    # --- Quick mode ---
    answer: str | None

    # --- Planning & Execution (Simple, Extended, Optimization) ---
    plan: dict | None
    execution_log: list[dict]
    artifacts: list[dict[str, Any]]
    last_result: dict | None

    # --- Debugging ---
    max_retries: int
    current_error: dict | None

    # --- Cost Gate ---
    optimization_state: str | None
    cost_analysis: dict | None
    strategy_choice: str | None

    # --- Validation ---
    validation_result: str | None
    validation_reason: str | None
    replan_count: int

    # --- Extended mode ---
    checkpoint_results: list[dict]
    checkpoint_action: str | None
    reflection: str | None

    # --- Experience ---
    cache_hit: bool
    cached_response: str | None

    # --- Observer ---
    observer_report: dict | None
    cancellation_token: Any  # CancellationToken (avoid circular import)

    # --- Knowledge ---
    knowledge_context: str | None

    # --- Sequential mode ---
    sequential_results: list[dict]  # accumulated Q&A results

    # --- Response ---
    response: str | None

    # --- Token Usage ---
    llm_usage: dict | None


# ── Mode taxonomy ─────────────────────────────────────────────────

BASE_MODES = frozenset({"quick", "simple", "extended", "optimization_required"})
META_MODES = frozenset({"deep", "sequential"})
ALL_MODES = BASE_MODES | META_MODES | frozenset({"off_topic"})


def is_base_mode(mode: str) -> bool:
    """Return True if mode is a directly executable (non-meta) mode."""
    return mode in BASE_MODES


def is_meta_mode(mode: str) -> bool:
    """Return True if mode is a metamode that orchestrates base modes."""
    return mode in META_MODES
