"""Shared node factories — plan, execute, debug, synthesize."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.cancellation import CancelledException
from mcpdb.llm.provider import LLMProvider, Message
from mcpdb.sandbox.executor import execute_python
from mcpdb.sandbox.security import get_security
from mcpdb.sources.base import QueryableSource
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.agent.nodes")


def _check_cancelled(state: AgentState) -> None:
    """Check if execution has been cancelled and raise if so."""
    token = state.get("cancellation_token")
    if token is not None:
        token.check()


# --- Plan Node ---

PLAN_PROMPT = """\
You are a data analysis planner. Create an execution plan for the user's question.

DATA SOURCES:
{source_context}

USER QUESTION: {question}
EXECUTION MODE: {mode_description}

AVAILABLE ACTIONS:
- "sql": Execute SQL on a database source (specify source_id)
- "python": Execute Python code (`df` = last SQL result as pandas DataFrame)
- "schema": Get schema details
- "sample": Get sample rows from a table

AVAILABLE PYTHON LIBRARIES:
{available_libraries}

RULES:
- You MUST produce the number of steps specified by the execution mode above. If the user asks for N steps, produce exactly N steps.
- For SQL: include the actual SQL code. Use the exact column and table names from the schema above.
- For Python: IMPORTANT — `df` contains ONLY the result from the IMMEDIATELY PRECEDING SQL step. You cannot access results from earlier steps. Each Python step can only use the `df` from the SQL step right before it. If you need data from multiple queries, combine them into one SQL query first, or re-query in the Python step's preceding SQL step.
- For Python: Use `plt.show()` to capture charts. Set `result_df = ...` to return a new DataFrame. Do NOT import os, sys, subprocess, or networking libraries.
- Plan steps as SQL→Python pairs: each SQL step fetches data, then the next Python step visualizes/analyzes it. Do NOT use variable names like `df1`, `df2` — only `df` is available.
- When counting rows, use SQL COUNT(*) — do not rely on schema metadata row counts which may be approximate.
- When computing ratios or percentages, use SQL directly for precision. When SQL already multiplies by 100 (e.g., `* 100.0`), name the column with a `_pct` suffix so Python and response text do NOT multiply by 100 again.
- Deviation formula: When computing deviation between estimated and actual values, use `(actual - estimated) / NULLIF(estimated, 0)` as the signed deviation. Divide by the estimated (baseline) value, not by the actual.
- For date calculations, use the actual date columns in the data (e.g., the year from the date column, NOT the current year).
- For large datasets (100K+ rows), prefer SQL or polars for aggregation over pandas.
- Ratio/percentage: AVG(a/b) ≠ SUM(a)/SUM(b). Choose based on question intent — "average ratio per row" uses AVG(a/b), "overall ratio" uses SUM(a)/SUM(b).
- MySQL median: Do NOT use PERCENTILE_CONT, PERCENTILE, or OFFSET with subqueries. Use ROW_NUMBER() window function: SELECT AVG(val) FROM (SELECT val, ROW_NUMBER() OVER (ORDER BY val) AS rn, COUNT(*) OVER() AS cnt FROM t) sub WHERE rn IN (FLOOR((cnt+1)/2), CEIL((cnt+1)/2)).
- NULL handling: Always filter NULLs with IS NOT NULL in WHERE clauses before aggregate functions like AVG, SUM on nullable columns.
- MySQL only_full_group_by: Every column in SELECT must be in GROUP BY or inside an aggregate function. Use CASE WHEN inside aggregate functions (e.g., SUM(CASE WHEN flag THEN 1 ELSE 0 END)) for conditional counting. Do NOT select raw columns alongside aggregates without grouping by them.
- MySQL reserved words: Do NOT use MySQL reserved words as table aliases. Reserved words include: dec, column, key, index, order, group, select, table, desc, asc, read, write, match, range, check, status, value, type. Use descriptive aliases instead (e.g., `elem_counts` instead of `dec`).
- For EDA or exploratory analysis: include diverse steps (distributions, correlations, outliers, trends). Use Python with matplotlib/seaborn for charts — always include `plt.show()` to capture them.

Respond with JSON only:
{{"analysis": "What the user wants", "approach": "How we'll get it", "steps": [{{"step_number": 1, "action": "sql", "source_id": "...", "description": "...", "code": "..."}}]}}
"""

# Mode descriptions for the plan prompt
MODE_DESCRIPTIONS = {
    "quick": "quick (1-2 steps, schema lookup only)",
    "simple": "simple (focused plan, 1-5 steps)",
    "extended": "extended (comprehensive analysis, 5-15 steps — use more steps for thorough coverage)",
    "optimization_required": "optimization (cost-aware, 2-8 steps with sampling)",
    "deep": "deep investigation (3-7 steps per sub-investigation)",
    "sequential": "sequential (answering a list of questions one by one, 1-5 steps each)",
}


def _get_mode_description(query_mode: str, question: str) -> str:
    """Get the mode description, respecting explicit step counts in the question."""
    import re
    # Check if user explicitly requested N steps
    match = re.search(r'(\d+)\s*(?:step|stage|phase)', question, re.IGNORECASE)
    if match:
        n = int(match.group(1))
        return f"comprehensive ({n} steps as requested by the user — produce exactly {n} steps)"

    return MODE_DESCRIPTIONS.get(query_mode, MODE_DESCRIPTIONS["simple"])


FALLBACK_PLAN_PROMPT = """\
You are a data analysis planner. The previous planning attempt failed.
Create a SIMPLE plan (1-3 steps only) for this question.

DATA SOURCES:
{source_context}

USER QUESTION: {question}

Rules:
- Use only "sql" actions
- Each step must have: step_number, action, source_id, description, code
- Keep SQL queries simple and standard

Respond with JSON ONLY, no other text:
{{"analysis": "...", "approach": "...", "steps": [{{"step_number": 1, "action": "sql", "source_id": "{default_source_id}", "description": "...", "code": "SELECT ..."}}]}}
"""


async def make_plan(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
    registry: SourceRegistry,
    experience_context: str | None = None,
    query_mode: str | None = None,
) -> AgentState:
    """Generate an execution plan via LLM.

    If experience_context is provided, it includes template/anti-pattern hints.
    query_mode controls the step range in the prompt (simple=1-5, extended=5-15).
    Retries once with a simpler prompt on failure. Falls back to a basic EDA
    plan if all LLM attempts fail.
    """
    callbacks.emit("plan/start")
    _check_cancelled(state)

    mode = query_mode or state.get("query_mode", "simple")
    mode_desc = _get_mode_description(mode, state["question"])

    security = get_security()
    prompt = PLAN_PROMPT.format(
        source_context=state.get("source_context", "No sources"),
        question=state["question"],
        mode_description=mode_desc,
        available_libraries=security.get_allowed_for_prompt(),
    )

    if experience_context:
        prompt = prompt + "\n\n" + experience_context

    knowledge_ctx = state.get("knowledge_context")
    if knowledge_ctx:
        prompt = prompt + "\n\n## DOMAIN KNOWLEDGE\n" + knowledge_ctx

    # Attempt 1: Normal plan prompt
    plan_result = await _try_plan(llm, prompt, callbacks, attempt=1)

    # Attempt 2: Retry with simpler prompt if first attempt failed
    if plan_result is None:
        default_source_id = ""
        sources = registry.list_sources()
        if sources:
            default_source_id = sources[0].source_id

        fallback_prompt = FALLBACK_PLAN_PROMPT.format(
            source_context=state.get("source_context", "No sources"),
            question=state["question"],
            default_source_id=default_source_id,
        )
        callbacks.emit("plan/retry", attempt=2)
        plan_result = await _try_plan(llm, fallback_prompt, callbacks, attempt=2)

    # If LLM planning worked, use it
    if plan_result is not None:
        steps = plan_result.get("steps", [])
        for step in steps:
            step.setdefault("status", "pending")
            step.setdefault("attempts", 0)

        state["plan"] = {
            "analysis": plan_result.get("analysis", ""),
            "approach": plan_result.get("approach", ""),
            "current_step_index": 0,
            "steps": steps,
        }

        if steps:
            callbacks.emit(
                "plan/ready",
                step_count=len(steps),
                analysis=plan_result.get("analysis", ""),
                approach=plan_result.get("approach", ""),
                steps=[
                    {
                        "step_number": s.get("step_number", i + 1),
                        "action": s.get("action", ""),
                        "description": s.get("description", ""),
                    }
                    for i, s in enumerate(steps)
                ],
            )
            return state

    # Attempt 3: Generate a hardcoded fallback plan for common queries
    fallback_steps = _generate_fallback_plan(state, registry)
    if fallback_steps:
        logger.info("Using fallback plan with %d steps", len(fallback_steps))
        state["plan"] = {
            "analysis": state["question"],
            "approach": "fallback_eda",
            "current_step_index": 0,
            "steps": fallback_steps,
        }
        callbacks.emit("plan/ready", step_count=len(fallback_steps))
    else:
        state["plan"] = {
            "analysis": state["question"],
            "approach": "fallback",
            "current_step_index": 0,
            "steps": [],
        }
        callbacks.emit("plan/error", error="All planning attempts failed")

    return state


async def _try_plan(
    llm: LLMProvider,
    prompt: str,
    callbacks: CallbackManager,
    attempt: int = 1,
    max_retries: int = 2,
) -> dict | None:
    """Try to generate a plan via LLM. Retries on transient errors."""
    import asyncio
    for retry in range(max_retries):
        try:
            result, usage = await asyncio.wait_for(
                llm.generate_json(
                    [Message(role="user", content=prompt)],
                    system="You are a data analysis planner. Respond with JSON only.",
                ),
                timeout=90.0,
            )
            return result
        except asyncio.TimeoutError:
            logger.warning("Planning attempt %d retry %d timed out", attempt, retry + 1)
            if retry >= max_retries - 1:
                callbacks.emit("plan/error", error="LLM call timed out", attempt=attempt)
                return None
        except Exception as e:
            if retry < max_retries - 1:
                delay = [2, 5][min(retry, 1)]
                logger.warning("Planning attempt %d retry %d failed, retrying in %ds: %s",
                               attempt, retry + 1, delay, e)
                await asyncio.sleep(delay)
            else:
                logger.warning("Planning attempt %d failed: %s", attempt, e)
                callbacks.emit("plan/error", error=str(e), attempt=attempt)
                return None
    return None


def _generate_fallback_plan(state: AgentState, registry: SourceRegistry) -> list[dict]:
    """Generate a basic fallback plan (schema exploration) without LLM.

    Works for EDA-type questions or when all LLM planning attempts fail.
    """
    sources = registry.list_sources()
    if not sources:
        return []

    source_id = sources[0].source_id
    source = registry.get_source(source_id)
    tables = sources[0].tables

    if not tables:
        return []

    steps: list[dict] = []
    step_num = 1

    # Step 1: List all tables with row counts
    steps.append({
        "step_number": step_num,
        "action": "schema",
        "source_id": source_id,
        "description": "Get full schema overview",
        "code": "",
        "status": "pending",
        "attempts": 0,
    })
    step_num += 1

    # Step 2: Sample first few tables (up to 5)
    for table in tables[:5]:
        steps.append({
            "step_number": step_num,
            "action": "sample",
            "source_id": source_id,
            "description": f"Sample rows from {table.name}",
            "table": table.name,
            "code": table.name,
            "status": "pending",
            "attempts": 0,
        })
        step_num += 1

    return steps


# --- Result Summary (metadata only, no data values) ---


def _summarize_result(result: dict[str, Any]) -> str:
    """Build a metadata-only summary of an execution result.

    Never includes actual data values — only shape, types, and statistics.
    This summary is safe to send to the LLM.
    """
    parts = []

    df = result.get("dataframe")
    if df is not None:
        import pandas as pd
        rows, cols = df.shape
        parts.append(f"{rows} rows x {cols} columns")
        # Column names and types — use dtypes series to handle duplicate columns safely
        col_info = ", ".join(f"{c} ({t})" for c, t in zip(df.columns, df.dtypes))
        parts.append(f"Columns: {col_info}")
        # Numeric stats (no actual values — just aggregates)
        # Use iloc for safe column access when duplicates exist
        numeric_cols = df.select_dtypes(include="number")
        if numeric_cols.shape[1] > 0:
            stats = []
            seen = set()
            for i, c in enumerate(numeric_cols.columns):
                col_key = f"{c}_{i}" if c in seen else c
                seen.add(c)
                col = numeric_cols.iloc[:, i]
                non_null = col.notna().sum()
                if non_null > 0:
                    stats.append(f"{c}: min={col.min():.4g}, max={col.max():.4g}, mean={col.mean():.4g}")
            if stats:
                parts.append("Stats: " + "; ".join(stats))
        # Null info
        null_counts = df.isnull().sum()
        nulls = {c: int(n) for c, n in null_counts.items() if n > 0}
        if nulls:
            parts.append(f"Nulls: {nulls}")
    elif result.get("output"):
        # For non-DataFrame results (schema, plain text), include the output
        # since it's metadata (schema descriptions), not data values
        output = str(result["output"])
        if len(output) > 500:
            output = output[:500] + "..."
        parts.append(output)

    if result.get("charts"):
        parts.append(f"[{len(result['charts'])} chart(s) generated]")

    return " | ".join(parts) if parts else "(no output)"


# --- Execute Node ---


async def execute_step(
    state: AgentState,
    callbacks: CallbackManager,
    registry: SourceRegistry,
) -> AgentState:
    """Execute the current plan step."""
    _check_cancelled(state)

    plan = state.get("plan")
    if not plan or not plan.get("steps"):
        return state

    idx = plan.get("current_step_index", 0)
    steps = plan["steps"]

    if idx >= len(steps):
        return state

    step = steps[idx]
    action = step.get("action", "sql")
    code = step.get("code", "")
    if not isinstance(code, str):
        code = str(code)
    source_id = step.get("source_id")

    callbacks.emit(
        "step/start",
        step_number=step.get("step_number", idx + 1),
        action=action,
        description=step.get("description", ""),
        code_preview=code[:200] if code else "",
    )

    start_time = time.time()

    try:
        if action == "sql":
            result = _execute_sql_step(code, source_id, registry)
        elif action == "python":
            result = _execute_python_step(code, state)
        elif action in ("schema", "sample"):
            result = _execute_info_step(action, source_id, step, registry)
        else:
            result = {"output": f"Unsupported action: '{action}'"}

        elapsed_ms = int((time.time() - start_time) * 1000)

        # Record success
        step["status"] = "success"
        summary = _summarize_result(result)
        step["result_summary"] = summary
        step["time_ms"] = elapsed_ms
        step["attempts"] = step.get("attempts", 0) + 1

        state["last_result"] = result
        state["execution_log"] = state.get("execution_log", []) + [{
            "step_number": step.get("step_number", idx + 1),
            "action": action,
            "code": code,
            "status": "success",
            "result_summary": summary,
            "time_ms": elapsed_ms,
        }]

        # Store DataFrame artifacts
        if "dataframe" in result:
            df = result["dataframe"]
            state["artifacts"] = state.get("artifacts", []) + [{
                "type": "table",
                "title": step.get("description", f"Step {idx + 1}"),
                "data": {
                    "columns": list(df.columns),
                    "rows": df.values.tolist(),
                    "total_rows": len(df),
                },
            }]

        # Store chart artifacts from Python steps
        for chart_b64 in result.get("charts", []):
            state["artifacts"] = state.get("artifacts", []) + [{
                "type": "chart",
                "title": step.get("description", f"Chart from step {idx + 1}"),
                "data": {"image_base64": chart_b64, "format": "png"},
            }]

        plan["current_step_index"] = idx + 1
        state["current_error"] = None

        callbacks.emit(
            "step/complete",
            step_number=step.get("step_number", idx + 1),
            time_ms=elapsed_ms,
            result_preview=summary[:200],
            rows=result.get("dataframe", None) is not None and len(result["dataframe"]) or 0,
        )

    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        step["attempts"] = step.get("attempts", 0) + 1

        state["current_error"] = {
            "step_index": idx,
            "action": action,
            "code": code,
            "error": str(e),
            "attempts": step["attempts"],
        }

        state["execution_log"] = state.get("execution_log", []) + [{
            "step_number": step.get("step_number", idx + 1),
            "action": action,
            "code": code,
            "status": "error",
            "error": str(e),
            "time_ms": elapsed_ms,
        }]

        callbacks.emit(
            "step/error",
            step_number=step.get("step_number", idx + 1),
            error=str(e),
        )

    return state


def _execute_sql_step(
    code: str, source_id: str | None, registry: SourceRegistry
) -> dict[str, Any]:
    """Execute a SQL step."""
    if not source_id:
        # Try the first queryable source
        qs = registry.get_queryable_sources()
        if not qs:
            raise ValueError("No queryable sources available")
        source = qs[0]
    else:
        source = registry.get_source(source_id)

    if not isinstance(source, QueryableSource):
        raise ValueError(f"Source '{source_id}' is not queryable")

    df = source.execute_query(code, max_rows=100)
    return {
        "output": df.to_string(max_colwidth=80),
        "dataframe": df,
        "row_count": len(df),
    }


def _execute_info_step(
    action: str, source_id: str | None, step: dict, registry: SourceRegistry
) -> dict[str, Any]:
    """Execute schema/sample info steps."""
    if not source_id:
        qs = registry.get_queryable_sources()
        if not qs:
            raise ValueError("No sources available")
        source = qs[0]
    else:
        source = registry.get_source(source_id)

    if action == "schema":
        return {"output": source.get_context_description()}
    elif action == "sample":
        table = step.get("table", step.get("code", ""))
        if isinstance(source, QueryableSource):
            df = source.get_sample(table, limit=5)
            return {"output": df.to_string(), "dataframe": df}
    return {"output": "Unknown info action"}


def _execute_python_step(code: str, state: AgentState) -> dict[str, Any]:
    """Execute a Python step in the sandbox."""
    # Get the last query result as context DataFrame
    context_df = None
    last_result = state.get("last_result")
    if last_result and "dataframe" in last_result:
        context_df = last_result["dataframe"]

    sandbox_result = execute_python(code, context_df=context_df, timeout=30)

    if not sandbox_result.success:
        raise RuntimeError(sandbox_result.error or "Python execution failed")

    result: dict[str, Any] = {"output": sandbox_result.stdout or "(no output)"}

    if sandbox_result.dataframe is not None:
        result["dataframe"] = sandbox_result.dataframe
        result["row_count"] = len(sandbox_result.dataframe)

    if sandbox_result.charts:
        result["charts"] = sandbox_result.charts

    return result


# --- Debug Node ---

DEBUG_PROMPT = """\
The following code failed. Fix it.

SOURCE CONTEXT:
{source_context}

CODE ({action}):
{code}

ERROR:
{error}

ATTEMPT: {attempt} of {max_retries}

AVAILABLE PYTHON LIBRARIES:
{available_libraries}

RULES:
- If this is a Python step, only use the libraries listed above. Do NOT import os, sys, subprocess, or networking libraries.
- If the error is an import violation, rewrite the code using only allowed libraries.
- IMPORTANT: Only `df` is available — it contains the result of the IMMEDIATELY PRECEDING SQL step. Variables like `df1`, `df2`, etc. DO NOT EXIST. If the code references undefined variables, rewrite it to use only `df`.
- If `df` is None or the error is about NoneType, the preceding step may have failed. Write a new SQL step instead that fetches the needed data — do NOT try to query databases from Python. Never import duckdb, sqlalchemy, pymysql, or any database library in Python steps. The Python sandbox has no database access.
- If this is a SQL step, fix the SQL syntax or logic.
- MySQL-specific: If "Unknown column" error — check the schema context for the correct column name, do not guess. If "only_full_group_by" error — ensure every non-aggregated column in SELECT is in GROUP BY. If "PERCENTILE" or "OFFSET subquery" error — use ROW_NUMBER() window function for median/percentile calculations. If SQL syntax error near an alias — the alias may be a MySQL reserved word (e.g., `dec`, `key`, `order`, `match`, `range`, `check`, `status`). Rename the alias to a non-reserved word.

Respond with JSON:
{{"error_analysis": "What went wrong", "corrected_code": "Fixed code"}}
"""


async def debug_step(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> AgentState:
    """Fix a failed step using LLM."""
    error = state.get("current_error")
    if not error:
        return state

    plan = state.get("plan", {})
    steps = plan.get("steps", [])
    idx = error["step_index"]
    max_retries = state.get("max_retries", 3)

    if error["attempts"] >= max_retries:
        # Give up on this step
        if idx < len(steps):
            steps[idx]["status"] = "failed"
        plan["current_step_index"] = idx + 1
        state["current_error"] = None
        callbacks.emit("debug/give_up", step_index=idx)
        return state

    callbacks.emit("debug/start", step_index=idx, attempt=error["attempts"])

    security = get_security()
    prompt = DEBUG_PROMPT.format(
        source_context=state.get("source_context", ""),
        action=error["action"],
        code=error["code"],
        error=error["error"],
        attempt=error["attempts"],
        max_retries=max_retries,
        available_libraries=security.get_allowed_for_prompt(),
    )

    import asyncio as _asyncio
    try:
        result, usage = await _asyncio.wait_for(
            llm.generate_json(
                [Message(role="user", content=prompt)],
                system="You are a code debugger. Respond with JSON only.",
            ),
            timeout=60.0,
        )

        corrected = result.get("corrected_code", error["code"])
        if idx < len(steps):
            steps[idx]["code"] = corrected
            steps[idx]["status"] = "pending"
        state["current_error"] = None

        callbacks.emit("debug/fixed", step_index=idx)

    except Exception as e:
        logger.warning("Debug LLM failed: %s", e)
        callbacks.emit("debug/error", step_index=idx, error=str(e))
        # Treat LLM failure as another failed attempt — advance if exhausted
        if error["attempts"] >= max_retries - 1:
            if idx < len(steps):
                steps[idx]["status"] = "failed"
            plan["current_step_index"] = idx + 1
            state["current_error"] = None

    return state


# --- Synthesize Node ---

SYNTHESIZE_CODE_PROMPT = """\
Write Python code that formats a clear, insightful answer to the user's question.

USER QUESTION: {question}

EXECUTION SUMMARY (metadata only — actual data is in the `artifacts` variable):
{results}

AVAILABLE VARIABLES (already defined, do NOT create them):
- `artifacts`: list of dicts. Each has "type" ("table" or "chart"), "title", and "data".
  - table artifact: data["columns"] = list of column names, data["rows"] = list of row lists, data["total_rows"] = int
  - chart artifact: data["image_base64"] = base64 string (just mention charts, don't decode)
- `execution_log`: list of step dicts

CRITICAL: All actual data values are in artifacts[i]["data"]["rows"]. You MUST read from
artifacts to get real numbers. Do NOT invent variable names or use placeholders.

EXAMPLE — how to read table data:
```
tables = [a for a in artifacts if a["type"] == "table"]
if tables:
    t = tables[0]
    cols = t["data"]["columns"]
    rows = t["data"]["rows"]
    # cols might be ["category", "total"], rows might be [["A", 100], ["B", 200]]
    for row in rows:
        print(f"- {{row[0]}}: {{row[1]}}")
```

RULES:
- print() your formatted answer as markdown text — every number must come from artifacts
- Include ALL items when listing results — never truncate or say "and N more"
- Interpret data, compute gaps, percentages, insights from the actual numbers
- If a column name ends with `_pct`, `_percent`, or `_rate` and values are already in percentage form (e.g., 8.73 meaning 8.73%), do NOT multiply by 100 again. Display as-is with a % suffix.
- Use markdown: headers (##), bold (**), bullet points, tables (| col | col |)
- If charts were generated, mention them: "See the chart below for the visualization."
- If some steps failed, note what worked and what didn't
- Do NOT import external libraries — use only builtins and what's already available

Respond with JSON:
{{"code": "python code here"}}
"""


async def synthesize(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> AgentState:
    """Generate the final response by running LLM-generated formatting code in sandbox.

    The LLM never sees actual data values — only result metadata (shapes, types, stats).
    It generates Python code that reads the artifacts and formats the answer.
    The sandbox executes this code with access to the real data.

    Fast path: for simple results (1 small table, no charts, no errors),
    format directly without an LLM call to save 10-30s.
    """
    callbacks.emit("synthesize/start")
    _check_cancelled(state)

    # Fast path: skip LLM for simple, small results
    fast_response = _try_fast_synthesize(state)
    if fast_response:
        logger.info("Synthesize fast path: skipping LLM call")
        state["response"] = fast_response
        callbacks.emit("synthesize/complete")
        return state

    # Build metadata-only summary for the LLM
    results_parts = []
    for log_entry in state.get("execution_log", []):
        status = log_entry.get("status", "unknown")
        summary = log_entry.get("result_summary", log_entry.get("error", ""))
        results_parts.append(
            f"Step {log_entry.get('step_number', '?')} ({log_entry.get('action', '?')}): "
            f"{status} | {summary}"
        )

    for artifact in state.get("artifacts", []):
        if artifact["type"] == "table":
            data = artifact["data"]
            results_parts.append(
                f"Table: {artifact.get('title', 'Result')} | "
                f"Columns: {data.get('columns', [])} | "
                f"Rows: {data.get('total_rows', 0)}"
            )
        elif artifact["type"] == "chart":
            results_parts.append(
                f"Chart: {artifact.get('title', 'Visualization')} [generated]"
            )

    results_text = "\n".join(results_parts) if results_parts else "No execution results."

    prompt = SYNTHESIZE_CODE_PROMPT.format(
        question=state["question"],
        results=results_text,
    )

    import asyncio
    for retry in range(3):
        try:
            result, usage = await asyncio.wait_for(
                llm.generate_json(
                    [Message(role="user", content=prompt)],
                    system="You are a data formatting expert. Generate Python code that formats analysis results into a clear answer. Respond with JSON only.",
                ),
                timeout=60.0,
            )

            format_code = result.get("code", "")
            if not format_code:
                raise ValueError("LLM returned empty formatting code")

            # Execute the formatting code in sandbox with access to artifacts
            response = _run_synthesize_code(format_code, state)
            state["response"] = response
            break

        except asyncio.TimeoutError:
            logger.warning("Synthesis LLM call timed out (retry %d)", retry + 1)
            if retry >= 2:
                state["response"] = _fallback_synthesize(state)
                callbacks.emit("synthesize/fallback", reason="LLM call timed out")
        except Exception as e:
            if retry < 2:
                delay = 1  # Quick retry — failures are usually JSON parsing, not rate limits
                logger.warning("Synthesis failed (retry %d), retrying in %ds: %s", retry + 1, delay, e)
                await asyncio.sleep(delay)
            else:
                logger.warning("Synthesis failed after 3 attempts: %s", e)
                # Fallback: build a basic response from result summaries
                state["response"] = _fallback_synthesize(state)
                callbacks.emit("synthesize/fallback", reason="all retries failed")

    callbacks.emit("synthesize/complete")
    return state


def _run_synthesize_code(code: str, state: AgentState) -> str:
    """Run LLM-generated formatting code in sandbox with artifact data."""
    # Build the wrapper that provides artifacts and execution_log to the code
    artifacts = state.get("artifacts", [])
    execution_log = state.get("execution_log", [])

    # Serialize artifacts for injection (tables include real data rows)
    import json as _json
    artifacts_json = _json.dumps(artifacts, default=str)
    log_json = _json.dumps(execution_log, default=str)

    wrapper = (
        "import json as _json\n"
        f"artifacts = _json.loads({_artifacts_literal(artifacts_json)})\n"
        f"execution_log = _json.loads({_artifacts_literal(log_json)})\n"
        "\n"
        f"{code}\n"
    )

    sandbox_result = execute_python(wrapper, timeout=15)

    if not sandbox_result.success:
        raise RuntimeError(f"Synthesis code failed: {sandbox_result.error}")

    output = (sandbox_result.stdout or "").strip()
    if not output:
        raise ValueError("Synthesis code produced no output")

    return output


def _artifacts_literal(json_str: str) -> str:
    """Safely embed a JSON string as a Python string literal."""
    return "'''" + json_str.replace("\\", "\\\\").replace("'''", "\\'\\'\\'") + "'''"


def _try_fast_synthesize(state: AgentState) -> str | None:
    """Try to format simple results directly, without an LLM call.

    Returns formatted response or None if results are too complex for fast path.
    Fast path criteria:
    - No charts (charts need interpretation)
    - No errors in execution
    - At most 2 table artifacts with ≤ 50 rows total
    - No deep/extended/optimization mode (these need richer synthesis)
    """
    mode = state.get("query_mode", "simple")
    if mode in ("deep", "extended", "optimization_required"):
        return None

    artifacts = state.get("artifacts", [])
    charts = [a for a in artifacts if a["type"] == "chart"]
    if charts:
        return None

    tables = [a for a in artifacts if a["type"] == "table"]
    if not tables or len(tables) > 2:
        return None

    # Check for errors in execution
    for entry in state.get("execution_log", []):
        if entry.get("status") == "error":
            return None

    # Check total row count
    total_rows = sum(t["data"].get("total_rows", 0) for t in tables)
    if total_rows > 50:
        return None

    # Format directly
    question = state.get("question", "")
    parts = [f"## Results\n"]

    for t in tables:
        data = t["data"]
        columns = data.get("columns", [])
        rows = data.get("rows", [])
        title = t.get("title", "Result")

        if not rows:
            parts.append(f"**{title}**: No data returned.\n")
            continue

        # Single value result
        if len(columns) == 1 and len(rows) == 1:
            parts.append(f"**{title}**: {rows[0][0]}\n")
            continue

        # Single row with few columns — key-value format
        if len(rows) == 1 and len(columns) <= 6:
            for col, val in zip(columns, rows[0]):
                parts.append(f"- **{col}**: {val}")
            parts.append("")
            continue

        # Table format
        if title and title != "Result":
            parts.append(f"**{title}**\n")

        # Header
        parts.append("| " + " | ".join(str(c) for c in columns) + " |")
        parts.append("| " + " | ".join("---" for _ in columns) + " |")

        # Rows
        for row in rows:
            cells = []
            for v in row:
                if v is None:
                    cells.append("")
                elif isinstance(v, float):
                    # Format floats nicely — avoid excessive decimal places
                    cells.append(f"{v:,.4g}" if abs(v) >= 0.01 or v == 0 else f"{v:.6g}")
                else:
                    cells.append(str(v))
            parts.append("| " + " | ".join(cells) + " |")
        parts.append("")

    return "\n".join(parts).strip()


def _fallback_synthesize(state: AgentState) -> str:
    """Build a response from artifacts when LLM code synthesis fails.

    This is the last resort — we format actual data from artifacts into
    markdown so the user always gets something useful.
    """
    # Try the fast-path first (works for small results regardless of mode)
    artifacts = state.get("artifacts", [])
    tables = [a for a in artifacts if a["type"] == "table"]
    charts = [a for a in artifacts if a["type"] == "chart"]

    parts = ["## Analysis Results\n"]

    # Format available table data
    for t in tables:
        data = t["data"]
        columns = data.get("columns", [])
        rows = data.get("rows", [])
        title = t.get("title", "Result")

        if not rows:
            continue

        if title and title != "Result":
            parts.append(f"**{title}**\n")

        # Single value
        if len(columns) == 1 and len(rows) == 1:
            parts.append(f"{columns[0]}: **{rows[0][0]}**\n")
            continue

        # Table format (cap at 50 rows for readability)
        parts.append("| " + " | ".join(str(c) for c in columns) + " |")
        parts.append("| " + " | ".join("---" for _ in columns) + " |")
        display_rows = rows[:50]
        for row in display_rows:
            cells = [str(v) if v is not None else "" for v in row]
            parts.append("| " + " | ".join(cells) + " |")
        if len(rows) > 50:
            parts.append(f"\n*Showing 50 of {len(rows)} rows.*\n")
        parts.append("")

    # Note any errors
    errors = [e for e in state.get("execution_log", []) if e.get("status") == "error"]
    if errors:
        parts.append(f"\n*Note: {len(errors)} step(s) encountered errors during execution.*")

    if charts:
        parts.append("\nSee the charts below for visual results.")

    result = "\n".join(parts).strip()
    # If we have no table data at all, fall back to execution log summaries
    if not tables:
        for entry in state.get("execution_log", []):
            status = entry.get("status", "unknown")
            summary = entry.get("result_summary", entry.get("error", ""))
            step_num = entry.get("step_number", "?")
            if status == "success" and summary:
                parts.append(f"**Step {step_num}**: {summary}")
        result = "\n\n".join(parts).strip()

    return result or "No results were generated for this query."
