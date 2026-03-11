"""Deep Analysis mode — multi-investigation research with reasoning loop.

Flow: create_blueprint → (classify + investigate → reason)* → synthesize report

Deep is a *metamode*: each investigation sub-question is independently
classified into a base mode (quick, simple, extended, optimization) and
dispatched to the appropriate runner.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcpdb.agent.state import AgentState, BASE_MODES
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.nodes.classify import classify_question
from mcpdb.agent.subgraphs import dispatch_base_mode
from mcpdb.llm.provider import LLMProvider, Message
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.agent.deep")

# Retry config for transient LLM errors (503, rate-limit, timeouts)
_MAX_RETRIES = 3
_RETRY_DELAYS = [2, 5, 10]  # seconds between retries

BLUEPRINT_PROMPT = """\
You are a senior data analyst creating a research blueprint.

DATA SOURCES:
{source_context}

RESEARCH QUESTION: {question}

Create a research blueprint with:
1. A clear research goal
2. 2-5 investigation questions that together will comprehensively answer the main question
3. For each investigation, specify what kind of analysis is needed
4. At least one investigation MUST include data visualization (charts, plots, distributions)

IMPORTANT:
- Keep investigations focused and non-overlapping
- Prefer fewer, targeted investigations over many broad ones
- Each investigation should be independent enough to run as a separate analysis
- Include visualization-focused investigations (e.g., "What does the distribution of X look like?", "How does Y trend over time?") — these produce charts that make the report more insightful

Respond with JSON:
{{"research_goal": "Overall goal", "investigations": [{{"id": 1, "question": "Sub-question", "approach": "How to investigate", "priority": "high|medium|low", "needs_visualization": true}}]}}
"""

REASONING_PROMPT = """\
You are reviewing completed investigations for a research project.

RESEARCH GOAL: {goal}

COMPLETED INVESTIGATIONS:
{completed}

REMAINING INVESTIGATIONS:
{remaining}

Based on what we've learned so far:
1. Are any remaining investigations redundant? (Mark as "skip")
2. Do we need new investigations based on discoveries? (Add as "add")
3. Is there enough evidence to answer the research question? (Set "sufficient" to true/false)

Respond with JSON:
{{"sufficient": false, "skip_ids": [], "new_investigations": [], "reasoning": "Why"}}
"""

DEEP_SYNTHESIZE_PROMPT = """\
Create a comprehensive research report answering the main question.

RESEARCH GOAL: {goal}

INVESTIGATION RESULTS:
{results}

REASONING NOTES:
{reasoning}

Format as a structured report with:
- Executive Summary
- Methodology
- Key Findings (numbered, with specific data values and statistics)
- Limitations
- Recommendations

Use markdown formatting. Reference specific numbers, percentages, and data points from the investigation results. The individual investigation results have already been shown to the user, so focus on synthesis and cross-cutting insights rather than repeating raw data. Charts and visualizations from investigations have been captured and displayed as images to the user.
"""


async def run_deep(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
    registry: SourceRegistry,
    max_iterations: int = 10,
) -> AgentState:
    """Execute the Deep Analysis mode.

    Creates a research blueprint, classifies and runs investigations,
    reasons about results, and synthesizes a comprehensive report.
    """
    callbacks.emit("deep/start")

    # 1. Create blueprint
    blueprint = await _create_blueprint(state, llm, callbacks)
    if not blueprint:
        state["response"] = "Could not create a research blueprint."
        callbacks.emit("deep/complete", investigations=0)
        return state

    goal = blueprint["research_goal"]
    investigations = blueprint["investigations"]

    # Store blueprint in state for experience caching
    state["blueprint"] = blueprint

    callbacks.emit("deep/blueprint", goal=goal, investigation_count=len(investigations))

    # 2. Investigation + reasoning loop
    completed: list[dict[str, Any]] = []
    all_artifacts: list[dict[str, Any]] = []
    reasoning_log: list[str] = []
    iteration = 0

    while iteration < max_iterations and investigations:
        iteration += 1

        # Pick next investigation
        inv = investigations.pop(0)
        inv_id = inv.get("id", iteration)
        inv_question = inv["question"]
        needs_viz = inv.get("needs_visualization", False)

        # Append visualization hint if needed
        full_question = inv_question
        if needs_viz:
            full_question += (
                " — Include a Python visualization step (matplotlib/seaborn) "
                "with plt.show() to create an informative chart."
            )

        # Classify this investigation to determine the best base mode
        classification = await classify_question(
            question=full_question,
            source_context=state.get("source_context", ""),
            llm=llm,
            allowed_modes=BASE_MODES,
        )
        submode = classification["mode"]

        callbacks.emit(
            "deep/investigation_start",
            investigation_id=inv_id,
            question=inv_question,
            approach=inv.get("approach", ""),
            submode=submode,
        )

        # Run investigation through the classified base mode
        inv_result = await _run_investigation(
            full_question, state, llm, callbacks, registry,
            submode=submode,
            key_entities=classification.get("key_entities", []),
        )

        inv_response = inv_result.get("response", "No results.")
        inv_artifacts = inv_result.get("artifacts", [])
        all_artifacts.extend(inv_artifacts)

        completed.append({
            "id": inv_id,
            "question": inv_question,
            "approach": inv.get("approach", ""),
            "result": inv_response,
            "submode": submode,
        })

        callbacks.emit(
            "deep/investigation_complete",
            investigation_id=inv_id,
            success=bool(inv_response),
            response=inv_response,
            has_artifacts=bool(inv_artifacts),
            artifact_count=len(inv_artifacts),
            artifacts=inv_artifacts,
            submode=submode,
        )

        # Reasoning checkpoint (after every 2 investigations or at end)
        if len(completed) % 2 == 0 or not investigations:
            reasoning = await _reason_about_results(
                goal, completed, investigations, llm, callbacks,
            )

            if reasoning:
                reasoning_log.append(reasoning.get("reasoning", ""))

                # Skip redundant investigations
                skip_ids = set(reasoning.get("skip_ids", []))
                if skip_ids:
                    investigations = [
                        i for i in investigations if i.get("id") not in skip_ids
                    ]

                # Add new investigations (normalize key names from LLM)
                for new_inv in reasoning.get("new_investigations", []):
                    new_inv.setdefault("id", 100 + len(completed) + len(investigations))
                    # LLM may use 'title' or 'topic' instead of 'question'
                    if "question" not in new_inv:
                        new_inv["question"] = (
                            new_inv.pop("title", None)
                            or new_inv.pop("topic", None)
                            or new_inv.pop("description", None)
                            or "Follow-up investigation"
                        )
                    investigations.append(new_inv)

                # Check if we have enough
                if reasoning.get("sufficient", False):
                    logger.info("Deep analysis: sufficient evidence at iteration %d", iteration)
                    callbacks.emit("deep/reasoning", sufficient=True, submode="quick")
                    break

                callbacks.emit("deep/reasoning", sufficient=False, submode="quick")

    # 3. Deep synthesis
    callbacks.emit("deep/synthesis_start")

    state = await _deep_synthesize(
        state, goal, completed, reasoning_log, llm, callbacks,
    )

    # Attach all investigation artifacts to the final state
    state["artifacts"] = state.get("artifacts", []) + all_artifacts

    callbacks.emit("deep/complete", investigations=len(completed))
    return state


async def _create_blueprint(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> dict[str, Any] | None:
    """Create a research blueprint via LLM (with retries)."""
    prompt = BLUEPRINT_PROMPT.format(
        source_context=state.get("source_context", "No sources"),
        question=state["question"],
    )

    for attempt in range(_MAX_RETRIES):
        try:
            result, usage = await llm.generate_json(
                [Message(role="user", content=prompt)],
                system="You are a senior data analyst. Respond with JSON only.",
            )
            return result
        except Exception as e:
            if attempt < _MAX_RETRIES - 1:
                delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                logger.warning("Blueprint creation failed (attempt %d/%d), retrying in %ds: %s",
                               attempt + 1, _MAX_RETRIES, delay, e)
                callbacks.emit("deep/retry", component="blueprint", attempt=attempt + 1, delay=delay)
                await asyncio.sleep(delay)
            else:
                logger.error("Blueprint creation failed after %d attempts: %s", _MAX_RETRIES, e)
    return None


async def _run_investigation(
    question: str,
    parent_state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
    registry: SourceRegistry,
    *,
    submode: str = "simple",
    key_entities: list[str] | None = None,
) -> dict[str, Any]:
    """Run a single investigation using the classified base mode.

    Returns dict with 'response' text and 'artifacts' list.
    """
    inv_state: AgentState = {
        "question": question,
        "source_context": parent_state.get("source_context", ""),
        "active_source_ids": parent_state.get("active_source_ids", []),
        "query_mode": submode,
        "target_sources": parent_state.get("active_source_ids", []),
        "requires_cross_source": False,
        "key_entities": key_entities or [],
        "response": None,
        "validation_result": None,
        "replan_count": 0,
        "artifacts": [],
        "execution_log": [],
        "max_retries": 2,  # Fewer retries for sub-investigations
    }

    try:
        inv_state = await dispatch_base_mode(inv_state, llm, callbacks, registry)
        return {
            "response": inv_state.get("response", "No results."),
            "artifacts": inv_state.get("artifacts", []),
        }
    except Exception as e:
        logger.warning("Investigation failed: %s", e)
        return {"response": f"Investigation failed: {e}", "artifacts": []}


async def _reason_about_results(
    goal: str,
    completed: list[dict[str, Any]],
    remaining: list[dict[str, Any]],
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> dict[str, Any] | None:
    """LLM reviews completed investigations and decides next steps (with retries)."""
    completed_text = "\n\n".join(
        f"Investigation {c['id']}: {c['question']}\n"
        f"Result: {c['result']}"
        for c in completed
    )

    remaining_text = "\n".join(
        f"- #{r.get('id', '?')}: {r.get('question', r.get('title', 'Unknown'))}"
        for r in remaining
    ) or "None"

    prompt = REASONING_PROMPT.format(
        goal=goal,
        completed=completed_text,
        remaining=remaining_text,
    )

    for attempt in range(_MAX_RETRIES):
        try:
            result, usage = await llm.generate_json(
                [Message(role="user", content=prompt)],
                system="You are a research advisor. Respond with JSON only.",
            )
            return result
        except Exception as e:
            if attempt < _MAX_RETRIES - 1:
                delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                logger.warning("Reasoning failed (attempt %d/%d), retrying in %ds: %s",
                               attempt + 1, _MAX_RETRIES, delay, e)
                callbacks.emit("deep/retry", component="reasoning", attempt=attempt + 1, delay=delay)
                await asyncio.sleep(delay)
            else:
                logger.warning("Reasoning failed after %d attempts: %s", _MAX_RETRIES, e)
    return None


async def _deep_synthesize(
    state: AgentState,
    goal: str,
    completed: list[dict[str, Any]],
    reasoning_log: list[str],
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> AgentState:
    """Synthesize a comprehensive research report."""
    results_text = "\n\n".join(
        f"### Investigation {c['id']}: {c['question']}\n{c['result']}"
        for c in completed
    )

    reasoning_text = "\n".join(reasoning_log) if reasoning_log else "No reasoning notes."

    prompt = DEEP_SYNTHESIZE_PROMPT.format(
        goal=goal,
        results=results_text,
        reasoning=reasoning_text,
    )

    for attempt in range(_MAX_RETRIES):
        try:
            text, usage = await llm.generate(
                [Message(role="user", content=prompt)],
                system="You are a senior data analyst writing a research report.",
            )
            state["response"] = text
            return state
        except Exception as e:
            if attempt < _MAX_RETRIES - 1:
                delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                logger.warning("Deep synthesis failed (attempt %d/%d), retrying in %ds: %s",
                               attempt + 1, _MAX_RETRIES, delay, e)
                callbacks.emit("deep/retry", component="synthesis", attempt=attempt + 1, delay=delay)
                await asyncio.sleep(delay)
            else:
                logger.warning("Deep synthesis failed after %d attempts: %s", _MAX_RETRIES, e)

    # Fallback: concatenate investigation results
    parts = [f"# Research Report: {goal}\n"]
    for c in completed:
        parts.append(f"## Investigation: {c['question']}\n{c['result']}\n")
    state["response"] = "\n".join(parts)

    return state
