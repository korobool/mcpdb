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
    query_mode: Literal["quick", "simple", "extended", "optimization_required", "deep", "off_topic"] | None
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

    # --- Response ---
    response: str | None

    # --- Token Usage ---
    llm_usage: dict | None
