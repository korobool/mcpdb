"""Deep Analysis mode — multi-investigation research with reasoning loop.

Flow: create_blueprint → (investigate → reason)* → synthesize report
"""

from __future__ import annotations

import logging
from typing import Any

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.subgraphs.simple import run_simple
from mcpdb.llm.provider import LLMProvider, Message
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.agent.deep")

BLUEPRINT_PROMPT = """\
You are a senior data analyst creating a research blueprint.

DATA SOURCES:
{source_context}

RESEARCH QUESTION: {question}

Create a research blueprint with:
1. A clear research goal
2. 3-7 investigation questions that together will comprehensively answer the main question
3. For each investigation, specify what kind of analysis is needed

Each investigation should be independent enough to run as a separate analysis.

Respond with JSON:
{{"research_goal": "Overall goal", "investigations": [{{"id": 1, "question": "Sub-question", "approach": "How to investigate", "priority": "high|medium|low"}}]}}
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
- Key Findings (numbered)
- Limitations
- Recommendations

Use markdown formatting.
"""


async def run_deep(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
    registry: SourceRegistry,
    max_iterations: int = 10,
) -> AgentState:
    """Execute the Deep Analysis mode.

    Creates a research blueprint, runs investigations, reasons about results,
    and synthesizes a comprehensive report.
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

    callbacks.emit("deep/blueprint", goal=goal, investigation_count=len(investigations))

    # 2. Investigation + reasoning loop
    completed: list[dict[str, Any]] = []
    reasoning_log: list[str] = []
    iteration = 0

    while iteration < max_iterations and investigations:
        iteration += 1

        # Pick next investigation
        inv = investigations.pop(0)
        inv_id = inv.get("id", iteration)
        inv_question = inv["question"]

        callbacks.emit(
            "deep/investigation_start",
            investigation_id=inv_id,
            question=inv_question,
        )

        # Run investigation as a Simple mode sub-agent
        inv_result = await _run_investigation(
            inv_question, state, llm, callbacks, registry,
        )

        completed.append({
            "id": inv_id,
            "question": inv_question,
            "approach": inv.get("approach", ""),
            "result": inv_result,
        })

        callbacks.emit(
            "deep/investigation_complete",
            investigation_id=inv_id,
            success=bool(inv_result),
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

                # Add new investigations
                for new_inv in reasoning.get("new_investigations", []):
                    new_inv.setdefault("id", 100 + len(completed) + len(investigations))
                    investigations.append(new_inv)

                # Check if we have enough
                if reasoning.get("sufficient", False):
                    logger.info("Deep analysis: sufficient evidence at iteration %d", iteration)
                    callbacks.emit("deep/reasoning", sufficient=True)
                    break

                callbacks.emit("deep/reasoning", sufficient=False)

    # 3. Deep synthesis
    callbacks.emit("deep/synthesis_start")

    state = await _deep_synthesize(
        state, goal, completed, reasoning_log, llm, callbacks,
    )

    callbacks.emit("deep/complete", investigations=len(completed))
    return state


async def _create_blueprint(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> dict[str, Any] | None:
    """Create a research blueprint via LLM."""
    prompt = BLUEPRINT_PROMPT.format(
        source_context=state.get("source_context", "No sources"),
        question=state["question"],
    )

    try:
        result, usage = await llm.generate_json(
            [Message(role="user", content=prompt)],
            system="You are a senior data analyst. Respond with JSON only.",
            max_tokens=2048,
        )
        return result
    except Exception as e:
        logger.error("Blueprint creation failed: %s", e)
        return None


async def _run_investigation(
    question: str,
    parent_state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
    registry: SourceRegistry,
) -> str:
    """Run a single investigation using Simple mode."""
    inv_state: AgentState = {
        "question": question,
        "source_context": parent_state.get("source_context", ""),
        "active_source_ids": parent_state.get("active_source_ids", []),
        "query_mode": "simple",
        "target_sources": parent_state.get("active_source_ids", []),
        "requires_cross_source": False,
        "key_entities": [],
        "response": None,
        "validation_result": None,
        "replan_count": 0,
        "artifacts": [],
        "execution_log": [],
        "max_retries": 2,  # Fewer retries for sub-investigations
    }

    try:
        inv_state = await run_simple(inv_state, llm, callbacks, registry)
        return inv_state.get("response", "No results.")
    except Exception as e:
        logger.warning("Investigation failed: %s", e)
        return f"Investigation failed: {e}"


async def _reason_about_results(
    goal: str,
    completed: list[dict[str, Any]],
    remaining: list[dict[str, Any]],
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> dict[str, Any] | None:
    """LLM reviews completed investigations and decides next steps."""
    completed_text = "\n\n".join(
        f"Investigation {c['id']}: {c['question']}\n"
        f"Result: {c['result'][:500]}"
        for c in completed
    )

    remaining_text = "\n".join(
        f"- #{r.get('id', '?')}: {r['question']}"
        for r in remaining
    ) or "None"

    prompt = REASONING_PROMPT.format(
        goal=goal,
        completed=completed_text,
        remaining=remaining_text,
    )

    try:
        result, usage = await llm.generate_json(
            [Message(role="user", content=prompt)],
            system="You are a research advisor. Respond with JSON only.",
            max_tokens=1024,
        )
        return result
    except Exception as e:
        logger.warning("Reasoning failed: %s", e)
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

    try:
        text, usage = await llm.generate(
            [Message(role="user", content=prompt)],
            system="You are a senior data analyst writing a research report.",
            max_tokens=4096,
        )
        state["response"] = text
    except Exception as e:
        logger.warning("Deep synthesis failed: %s", e)
        # Fallback: concatenate investigation results
        parts = [f"# Research Report: {goal}\n"]
        for c in completed:
            parts.append(f"## Investigation: {c['question']}\n{c['result']}\n")
        state["response"] = "\n".join(parts)

    return state
