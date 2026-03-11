"""Sequential mode — answer a list of questions one by one with accumulating context.

Flow: parse_questions → (run_simple with prior_context)* → synthesize_sequence

Unlike deep mode (which auto-generates sub-questions from a blueprint),
sequential mode uses user-provided questions and builds on the context
from each previous answer.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.subgraphs.simple import run_simple
from mcpdb.llm.provider import LLMProvider, Message
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.agent.sequential")

# Retry config for transient LLM errors
_MAX_RETRIES = 3
_RETRY_DELAYS = [2, 5, 10]

# Limits
MAX_QUESTIONS = 20
MAX_PRIOR_CONTEXT_CHARS = 4000
MAX_ANSWER_SUMMARY_CHARS = 500

SEQUENTIAL_SYNTHESIZE_PROMPT = """\
You are synthesizing results from a sequential data analysis session.

The user asked {question_count} questions in sequence, each building on previous answers.

QUESTIONS AND ANSWERS:
{results}

Write a unified summary that:
- Highlights key findings across all questions
- Notes patterns, trends, or connections between answers
- Identifies any contradictions or surprises
- Provides actionable conclusions

Use markdown formatting. Reference specific numbers and data points from the answers.
The individual answers have already been shown to the user, so focus on synthesis
and cross-cutting insights rather than repeating raw data.
"""

# Pattern to strip numbered/bulleted prefixes from lines
_PREFIX_RE = re.compile(r"^\s*(?:\d+[\.\)]\s*|[-*]\s+)")


def parse_questions(text: str) -> list[str]:
    """Split multi-line input into individual questions.

    Handles: newline-separated, numbered lists (1. 2. 3.), bullet points (- *).
    Strips blank lines and numbering prefixes.
    """
    lines = text.strip().split("\n")
    questions = []
    for line in lines:
        cleaned = _PREFIX_RE.sub("", line).strip()
        if cleaned:
            questions.append(cleaned)
    return questions[:MAX_QUESTIONS]


async def run_sequential(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
    registry: SourceRegistry,
) -> AgentState:
    """Execute Sequential mode.

    Parses the question into a list, answers each one by one with
    accumulating context, streams intermediate results, then synthesizes.
    """
    questions = parse_questions(state["question"])

    # Degenerate case: single question → just run simple
    if len(questions) <= 1:
        state["query_mode"] = "simple"
        if questions:
            state["question"] = questions[0]
        return await run_simple(state, llm, callbacks, registry)

    callbacks.emit("sequential/start", question_count=len(questions))

    results: list[dict[str, Any]] = []
    all_artifacts: list[dict[str, Any]] = []
    all_execution_log: list[dict] = []

    for i, question in enumerate(questions):
        callbacks.emit(
            "sequential/step_start",
            step_index=i,
            question=question,
            total=len(questions),
        )

        prior_context = _build_prior_context(results)
        step_result = await _run_step(
            question, state, prior_context, llm, callbacks, registry,
        )

        results.append({
            "index": i,
            "question": question,
            "response": step_result.get("response", "No results."),
            "artifacts": step_result.get("artifacts", []),
        })
        all_artifacts.extend(step_result.get("artifacts", []))
        all_execution_log.extend(step_result.get("execution_log", []))

        callbacks.emit(
            "sequential/step_complete",
            step_index=i,
            question=question,
            response=step_result.get("response", ""),
            artifacts=step_result.get("artifacts", []),
            has_artifacts=bool(step_result.get("artifacts")),
            artifact_count=len(step_result.get("artifacts", [])),
        )

    # Final synthesis
    callbacks.emit("sequential/synthesis_start")
    state = await _sequential_synthesize(state, results, llm, callbacks)

    state["artifacts"] = state.get("artifacts", []) + all_artifacts
    state["execution_log"] = all_execution_log
    state["sequential_results"] = results

    callbacks.emit("sequential/complete", questions_answered=len(results))
    return state


async def _run_step(
    question: str,
    parent_state: AgentState,
    prior_context: str,
    llm: LLMProvider,
    callbacks: CallbackManager,
    registry: SourceRegistry,
) -> dict[str, Any]:
    """Run a single question through simple mode with prior Q&A context injected."""
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
        "max_retries": 2,
    }

    # Inject prior context so make_plan sees it
    if prior_context:
        existing = parent_state.get("knowledge_context", "") or ""
        inv_state["knowledge_context"] = (
            (existing + "\n\n" if existing else "") + prior_context
        )

    try:
        inv_state = await run_simple(inv_state, llm, callbacks, registry)
        return {
            "response": inv_state.get("response", "No results."),
            "artifacts": inv_state.get("artifacts", []),
            "execution_log": inv_state.get("execution_log", []),
        }
    except Exception as e:
        logger.warning("Sequential step failed: %s", e)
        return {"response": f"Step failed: {e}", "artifacts": [], "execution_log": []}


def _build_prior_context(results: list[dict[str, Any]]) -> str:
    """Build a context string from previously answered questions.

    Truncates older answers more aggressively to stay within budget.
    """
    if not results:
        return ""

    parts = ["PREVIOUS Q&A CONTEXT (from earlier steps in this sequence):"]
    total_chars = 0

    for r in results:
        answer = r.get("response", "")
        # Truncate answer summary — older ones get less space
        max_len = MAX_ANSWER_SUMMARY_CHARS
        if len(results) > 3:
            # Progressive truncation: first answers get less space
            position_ratio = (r["index"] + 1) / len(results)
            max_len = int(MAX_ANSWER_SUMMARY_CHARS * (0.3 + 0.7 * position_ratio))

        if len(answer) > max_len:
            answer = answer[:max_len] + "..."

        entry = f"---\nQ{r['index'] + 1}: {r['question']}\nA{r['index'] + 1}: {answer}\n"

        if total_chars + len(entry) > MAX_PRIOR_CONTEXT_CHARS:
            parts.append("---\n[Earlier answers truncated for brevity]")
            break

        parts.append(entry)
        total_chars += len(entry)

    return "\n".join(parts)


async def _sequential_synthesize(
    state: AgentState,
    results: list[dict[str, Any]],
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> AgentState:
    """Synthesize a final summary from all Q&A pairs."""
    results_text = "\n\n".join(
        f"### Question {r['index'] + 1}: {r['question']}\n{r['response']}"
        for r in results
    )

    prompt = SEQUENTIAL_SYNTHESIZE_PROMPT.format(
        question_count=len(results),
        results=results_text,
    )

    for attempt in range(_MAX_RETRIES):
        try:
            text, usage = await llm.generate(
                [Message(role="user", content=prompt)],
                system="You are a senior data analyst writing a synthesis of sequential analysis results.",
            )
            state["response"] = text
            return state
        except Exception as e:
            if attempt < _MAX_RETRIES - 1:
                delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                logger.warning(
                    "Sequential synthesis failed (attempt %d/%d), retrying in %ds: %s",
                    attempt + 1, _MAX_RETRIES, delay, e,
                )
                callbacks.emit(
                    "sequential/retry",
                    component="synthesis", attempt=attempt + 1, delay=delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.warning(
                    "Sequential synthesis failed after %d attempts: %s",
                    _MAX_RETRIES, e,
                )

    # Fallback: concatenate individual results
    parts = ["# Sequential Analysis Summary\n"]
    for r in results:
        parts.append(f"## Question {r['index'] + 1}: {r['question']}\n{r['response']}\n")
    state["response"] = "\n".join(parts)
    return state
