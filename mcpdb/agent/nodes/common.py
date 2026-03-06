"""Shared node factories — plan, execute, debug, synthesize."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.llm.provider import LLMProvider, Message
from mcpdb.sandbox.executor import execute_python
from mcpdb.sandbox.security import get_security
from mcpdb.sources.base import QueryableSource
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.agent.nodes")


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
- When computing ratios or percentages, use SQL directly for precision.
- For date calculations, use the actual date columns in the data (e.g., the year from the date column, NOT the current year).
- For large datasets (100K+ rows), prefer SQL or polars for aggregation over pandas.
- Ratio/percentage: AVG(a/b) ≠ SUM(a)/SUM(b). Choose based on question intent — "average ratio per row" uses AVG(a/b), "overall ratio" uses SUM(a)/SUM(b).
- MySQL median: Do NOT use PERCENTILE_CONT or OFFSET with subqueries. Use ROW_NUMBER() window function: SELECT AVG(val) FROM (SELECT val, ROW_NUMBER() OVER (ORDER BY val) AS rn, COUNT(*) OVER() AS cnt FROM t) sub WHERE rn IN (FLOOR((cnt+1)/2), CEIL((cnt+1)/2)).
- NULL handling: Always filter NULLs with IS NOT NULL in WHERE clauses before aggregate functions like AVG, SUM on nullable columns.
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
            result, usage = await llm.generate_json(
                [Message(role="user", content=prompt)],
                system="You are a data analysis planner. Respond with JSON only.",
            )
            return result
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


# --- Execute Node ---


async def execute_step(
    state: AgentState,
    callbacks: CallbackManager,
    registry: SourceRegistry,
) -> AgentState:
    """Execute the current plan step."""
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
        step["result_preview"] = str(result.get("output", ""))
        step["time_ms"] = elapsed_ms
        step["attempts"] = step.get("attempts", 0) + 1

        state["last_result"] = result
        state["execution_log"] = state.get("execution_log", []) + [{
            "step_number": step.get("step_number", idx + 1),
            "action": action,
            "code": code,
            "status": "success",
            "result_preview": step["result_preview"],
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
            result_preview=step["result_preview"][:200] if step.get("result_preview") else "",
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
- If `df` is None or the error is about NoneType, the preceding step may have failed. Make the code self-contained by querying the data within the Python step using pandas or re-using `df` safely.
- If this is a SQL step, fix the SQL syntax or logic.

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

    try:
        result, usage = await llm.generate_json(
            [Message(role="user", content=prompt)],
            system="You are a code debugger. Respond with JSON only.",
        )

        corrected = result.get("corrected_code", error["code"])
        if idx < len(steps):
            steps[idx]["code"] = corrected
            steps[idx]["status"] = "pending"
        state["current_error"] = None

        callbacks.emit("debug/fixed", step_index=idx)

    except Exception as e:
        logger.warning("Debug LLM failed: %s", e)
        # Count this as another attempt
        callbacks.emit("debug/error", step_index=idx, error=str(e))

    return state


# --- Synthesize Node ---

SYNTHESIZE_PROMPT = """\
Synthesize a clear, complete answer to the user's question based on the execution results below.

USER QUESTION: {question}

EXECUTION RESULTS:
{results}

Guidelines:
- Directly answer the question
- When the user asks to LIST items, include EVERY item from the results. Never truncate, summarize, or say "and N more".
- Highlight key findings
- Use markdown formatting
- Interpret data, don't just repeat raw numbers
- If some steps failed, note what worked and what didn't
"""


async def synthesize(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> AgentState:
    """Generate the final user-facing response."""
    callbacks.emit("synthesize/start")

    # Build results summary
    results_parts = []
    for log_entry in state.get("execution_log", []):
        status = log_entry.get("status", "unknown")
        preview = log_entry.get("result_preview", log_entry.get("error", ""))
        results_parts.append(
            f"Step {log_entry.get('step_number', '?')} ({log_entry.get('action', '?')}): "
            f"{status}\n{preview}"
        )

    # Include artifact data
    for artifact in state.get("artifacts", []):
        if artifact["type"] == "table":
            data = artifact["data"]
            results_parts.append(
                f"\nTable: {artifact.get('title', 'Result')}\n"
                f"Columns: {data.get('columns', [])}\n"
                f"Rows: {data.get('total_rows', 0)}"
            )

    results_text = "\n\n".join(results_parts) if results_parts else "No execution results."

    prompt = SYNTHESIZE_PROMPT.format(
        question=state["question"],
        results=results_text,
    )

    import asyncio
    for retry in range(3):
        try:
            text, usage = await llm.generate(
                [Message(role="user", content=prompt)],
                system="You are a data analyst. Provide clear, insightful answers.",
            )
            state["response"] = text
            break
        except Exception as e:
            if retry < 2:
                delay = [2, 5][min(retry, 1)]
                logger.warning("Synthesis failed (retry %d), retrying in %ds: %s", retry + 1, delay, e)
                await asyncio.sleep(delay)
            else:
                logger.warning("Synthesis failed after 3 attempts: %s", e)
                state["response"] = f"Analysis completed but synthesis failed: {e}"

    callbacks.emit("synthesize/complete")
    return state
