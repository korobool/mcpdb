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
from mcpdb.sources.base import QueryableSource
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.agent.nodes")


# --- Plan Node ---

PLAN_PROMPT = """\
You are a data analysis planner. Create an execution plan for the user's question.

DATA SOURCES:
{source_context}

USER QUESTION: {question}
EXECUTION MODE: simple (focused plan, 1-5 steps)

AVAILABLE ACTIONS:
- "sql": Execute SQL on a database source (specify source_id)
- "python": Execute Python code (pandas, numpy, matplotlib, seaborn available; `df` = last SQL result)
- "schema": Get schema details
- "sample": Get sample rows from a table

RULES:
- For SQL: include the actual SQL code
- For Python: `df` contains the last SQL result as a pandas DataFrame. Use `plt.show()` to capture charts. Set `result_df = ...` to return a new DataFrame.
- Use exact column/table names from the schemas above

Respond with JSON only:
{{"analysis": "What the user wants", "approach": "How we'll get it", "steps": [{{"step_number": 1, "action": "sql", "source_id": "...", "description": "...", "code": "..."}}]}}
"""


async def make_plan(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
    registry: SourceRegistry,
    experience_context: str | None = None,
) -> AgentState:
    """Generate an execution plan via LLM.

    If experience_context is provided, it includes template/anti-pattern hints.
    """
    callbacks.emit("plan/start")

    prompt = PLAN_PROMPT.format(
        source_context=state.get("source_context", "No sources"),
        question=state["question"],
    )

    if experience_context:
        prompt = prompt + "\n\n" + experience_context

    try:
        result, usage = await llm.generate_json(
            [Message(role="user", content=prompt)],
            system="You are a data analysis planner. Respond with JSON only.",
            max_tokens=2048,
        )

        steps = result.get("steps", [])
        for step in steps:
            step.setdefault("status", "pending")
            step.setdefault("attempts", 0)

        state["plan"] = {
            "analysis": result.get("analysis", ""),
            "approach": result.get("approach", ""),
            "current_step_index": 0,
            "steps": steps,
        }

        callbacks.emit("plan/ready", step_count=len(steps))

    except Exception as e:
        logger.warning("Planning failed: %s", e)
        state["plan"] = {
            "analysis": state["question"],
            "approach": "fallback",
            "current_step_index": 0,
            "steps": [],
        }
        callbacks.emit("plan/error", error=str(e))

    return state


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

    callbacks.emit("step/start", step_number=step.get("step_number", idx + 1), action=action)

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
        step["result_preview"] = str(result.get("output", ""))[:200]
        step["time_ms"] = elapsed_ms
        step["attempts"] = step.get("attempts", 0) + 1

        state["last_result"] = result
        state["execution_log"] = state.get("execution_log", []) + [{
            "step_number": step.get("step_number", idx + 1),
            "action": action,
            "code": code[:200],
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
                    "rows": df.values.tolist()[:50],
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
            "code": code[:200],
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
        "output": df.to_string(max_colwidth=50)[:500],
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

    prompt = DEBUG_PROMPT.format(
        source_context=state.get("source_context", ""),
        action=error["action"],
        code=error["code"],
        error=error["error"],
        attempt=error["attempts"],
        max_retries=max_retries,
    )

    try:
        result, usage = await llm.generate_json(
            [Message(role="user", content=prompt)],
            system="You are a code debugger. Respond with JSON only.",
            max_tokens=2048,
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
Synthesize a clear, concise answer to the user's question based on the execution results below.

USER QUESTION: {question}

EXECUTION RESULTS:
{results}

Guidelines:
- Directly answer the question
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

    try:
        text, usage = await llm.generate(
            [Message(role="user", content=prompt)],
            system="You are a data analyst. Provide clear, insightful answers.",
            max_tokens=2048,
        )
        state["response"] = text

    except Exception as e:
        logger.warning("Synthesis failed: %s", e)
        state["response"] = f"Analysis completed but synthesis failed: {e}"

    callbacks.emit("synthesize/complete")
    return state
