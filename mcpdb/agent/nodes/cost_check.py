"""Cost check node — evaluate query cost before execution."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.llm.provider import LLMProvider, Message
from mcpdb.sources.base import QueryableSource
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.agent.cost_check")


@dataclass
class CostAnalysis:
    """Result of cost analysis for a query plan."""
    decision: str  # "not_required", "recommended", "necessary"
    reason: str = ""
    estimated_rows: int | None = None
    has_limit: bool = False
    has_sampling: bool = False
    large_tables: list[str] = field(default_factory=list)
    explain_results: list[dict[str, Any]] = field(default_factory=list)


# --- Layer 0: Fast regex scan ---


_LIMIT_PATTERN = re.compile(r"\bLIMIT\s+\d+", re.IGNORECASE)
_TOP_PATTERN = re.compile(r"\bTOP\s+\d+", re.IGNORECASE)
_SAMPLE_PATTERN = re.compile(r"\bTABLESAMPLE\b|\bSAMPLE\s*\(", re.IGNORECASE)
_AGGREGATE_PATTERN = re.compile(
    r"\b(COUNT|SUM|AVG|MIN|MAX|GROUP\s+BY)\b", re.IGNORECASE
)


def fast_scan(code: str) -> dict[str, bool]:
    """Layer 0: Quick regex scan for cost-related patterns."""
    return {
        "has_limit": bool(_LIMIT_PATTERN.search(code) or _TOP_PATTERN.search(code)),
        "has_sampling": bool(_SAMPLE_PATTERN.search(code)),
        "has_aggregate": bool(_AGGREGATE_PATTERN.search(code)),
    }


# --- Layer 1: EXPLAIN integration ---


def run_explain(
    code: str, source_id: str | None, registry: SourceRegistry,
) -> dict[str, Any] | None:
    """Layer 1: Run EXPLAIN on a SQL query and parse the result."""
    try:
        source = _get_source(source_id, registry)
        if not isinstance(source, QueryableSource):
            return None

        # Get the dialect for EXPLAIN prefix
        dialect = getattr(source, "dialect", None)
        if dialect is None:
            return None

        explain_prefix = dialect.get_explain_prefix()
        explain_sql = f"{explain_prefix} {code}"

        df = source.execute_query(explain_sql, max_rows=100)
        raw_output = df.to_string()

        # parse_explain_output expects list[dict] (rows from the EXPLAIN result)
        rows = df.to_dict(orient="records")
        explain_result = dialect.parse_explain_output(rows)

        return {
            "estimated_rows": explain_result.estimated_rows,
            "estimated_cost": explain_result.estimated_cost,
            "scan_type": explain_result.scan_type,
            "uses_index": explain_result.uses_index,
            "warnings": explain_result.warnings,
            "raw": raw_output[:500],
        }
    except Exception as e:
        logger.debug("EXPLAIN failed for query: %s", e)
        return None


# --- Layer 3: Heuristic fallback ---


def heuristic_check(
    step: dict[str, Any],
    source_id: str | None,
    registry: SourceRegistry,
    large_table_threshold: int = 1_000_000,
) -> CostAnalysis:
    """Layer 3: Heuristic cost estimate based on table sizes and query patterns."""
    code = step.get("code", "")
    scan = fast_scan(code)

    # If query has LIMIT or SAMPLING, it's likely cheap
    if scan["has_limit"] or scan["has_sampling"]:
        return CostAnalysis(
            decision="not_required",
            reason="Query has LIMIT or SAMPLING clause",
            has_limit=scan["has_limit"],
            has_sampling=scan["has_sampling"],
        )

    # Check for large tables
    large_tables = _find_large_tables(code, source_id, registry, large_table_threshold)

    if not large_tables:
        return CostAnalysis(
            decision="not_required",
            reason="No large tables detected",
        )

    # Aggregate on large table — recommended but not necessary
    if scan["has_aggregate"]:
        return CostAnalysis(
            decision="recommended",
            reason=f"Aggregate query on large table(s): {', '.join(large_tables)}",
            large_tables=large_tables,
        )

    # Full scan on large table — necessary
    return CostAnalysis(
        decision="necessary",
        reason=f"Potential full scan on large table(s): {', '.join(large_tables)}",
        large_tables=large_tables,
    )


# --- Layer 2: LLM cost check ---


COST_CHECK_PROMPT = """\
Analyze this SQL query's potential cost.

QUERY:
{code}

TABLE INFO:
{table_info}

EXPLAIN OUTPUT:
{explain_output}

Respond with JSON:
{{"decision": "not_required|recommended|necessary", "reason": "...", "estimated_rows": <number or null>}}

- "not_required": Query is cheap (small tables, good indexes, has LIMIT)
- "recommended": Query might be expensive (large table aggregates, but indexes may help)
- "necessary": Query is definitely expensive (full scans on large tables, cross joins, no indexes)
"""


async def llm_cost_check(
    step: dict[str, Any],
    source_id: str | None,
    registry: SourceRegistry,
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> CostAnalysis:
    """Layer 2: LLM-based cost analysis using EXPLAIN output."""
    code = step.get("code", "")

    # Get EXPLAIN output
    explain = run_explain(code, source_id, registry)
    explain_output = explain.get("raw", "EXPLAIN unavailable") if explain else "EXPLAIN unavailable"

    # Get table info
    table_info = _get_table_info(source_id, registry)

    prompt = COST_CHECK_PROMPT.format(
        code=code,
        table_info=table_info,
        explain_output=explain_output,
    )

    try:
        result, usage = await llm.generate_json(
            [Message(role="user", content=prompt)],
            system="You are a database performance analyst. Respond with JSON only.",
            max_tokens=256,
        )

        analysis = CostAnalysis(
            decision=result.get("decision", "not_required"),
            reason=result.get("reason", ""),
            estimated_rows=result.get("estimated_rows"),
        )

        if explain:
            analysis.explain_results.append(explain)

        return analysis

    except Exception as e:
        logger.warning("LLM cost check failed: %s", e)
        # Fall back to heuristic
        return heuristic_check(step, source_id, registry)


# --- Main cost check node ---


async def cost_check(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
    registry: SourceRegistry,
    large_table_threshold: int = 1_000_000,
) -> AgentState:
    """Cost check node — evaluate all SQL steps before execution.

    Routing:
    - not_required → proceed to execute
    - recommended/necessary → strategy_gate
    """
    callbacks.emit("cost_check/start")

    plan = state.get("plan", {})
    steps = plan.get("steps", [])

    analyses = []
    worst_decision = "not_required"
    decision_rank = {"not_required": 0, "recommended": 1, "necessary": 2}

    for step in steps:
        if step.get("action") != "sql":
            continue

        source_id = step.get("source_id")
        code = step.get("code", "")

        # Layer 0: Fast scan
        scan = fast_scan(code)
        if scan["has_limit"] or scan["has_sampling"]:
            analyses.append(CostAnalysis(
                decision="not_required",
                reason="Has LIMIT/SAMPLING",
                has_limit=scan["has_limit"],
                has_sampling=scan["has_sampling"],
            ))
            continue

        # Layer 3: Heuristic
        heuristic = heuristic_check(step, source_id, registry, large_table_threshold)

        if heuristic.decision == "not_required":
            analyses.append(heuristic)
            continue

        # Layer 1+2: EXPLAIN + LLM for potentially expensive queries
        explain = run_explain(code, source_id, registry)
        if explain and explain.get("estimated_rows", 0) and explain["estimated_rows"] < large_table_threshold:
            analyses.append(CostAnalysis(
                decision="not_required",
                reason="EXPLAIN shows reasonable cost",
                explain_results=[explain],
            ))
            continue

        # Use LLM for final determination
        analysis = await llm_cost_check(step, source_id, registry, llm, callbacks)
        analyses.append(analysis)

        if decision_rank.get(analysis.decision, 0) > decision_rank.get(worst_decision, 0):
            worst_decision = analysis.decision

    state["cost_analysis"] = {
        "decision": worst_decision,
        "analyses": [
            {"decision": a.decision, "reason": a.reason, "large_tables": a.large_tables}
            for a in analyses
        ],
    }

    callbacks.emit("cost_check/complete", decision=worst_decision)
    return state


# --- Helpers ---


def _get_source(source_id: str | None, registry: SourceRegistry) -> Any:
    if source_id:
        return registry.get_source(source_id)
    qs = registry.get_queryable_sources()
    return qs[0] if qs else None


def _find_large_tables(
    code: str, source_id: str | None, registry: SourceRegistry,
    threshold: int,
) -> list[str]:
    """Find tables referenced in the query that exceed the row threshold."""
    try:
        source = _get_source(source_id, registry)
        if not source:
            return []
        metadata = source.get_metadata()
        large = []
        for table in metadata.tables:
            if table.row_count and table.row_count >= threshold:
                # Check if this table is referenced in the query
                if table.name.lower() in code.lower():
                    large.append(table.name)
        return large
    except Exception:
        return []


def _get_table_info(source_id: str | None, registry: SourceRegistry) -> str:
    """Get table info text for LLM prompt."""
    try:
        source = _get_source(source_id, registry)
        if not source:
            return "No source available"
        return source.get_context_description()
    except Exception:
        return "Table info unavailable"
