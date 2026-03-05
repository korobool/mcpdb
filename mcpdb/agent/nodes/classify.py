"""Classify node — routes questions to the appropriate thinking mode."""

from __future__ import annotations

import json
import logging
from typing import Any

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.llm.provider import LLMProvider, Message

logger = logging.getLogger("mcpdb.agent.classify")

CLASSIFY_PROMPT = """\
You are a query classifier for a multi-source data assistant.

ACTIVE DATA SOURCES:
{source_context}

USER QUESTION: {question}

AVAILABLE MODES:
1. **quick** — Answer from known context (schema questions, previous results)
2. **simple** — 1-5 execution steps (DEFAULT for most data questions)
3. **extended** — 3-10 steps for comprehensive analysis, EDA, root cause
4. **optimization_required** — Large table operations (>1M rows, no narrow filters)
5. **deep** — Multi-investigation research (e.g., "investigate customer churn", "comprehensive audit")

Respond with JSON only:
{{"mode": "quick|simple|extended|optimization_required|deep", "reasoning": "Why this mode", "target_sources": ["source_id"], "requires_cross_source": false, "key_entities": ["tables/columns mentioned"]}}
"""


async def classify(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> AgentState:
    """Classify a question into a thinking mode."""
    callbacks.emit("classify/start", question=state["question"])

    question = state["question"]
    source_context = state.get("source_context", "No sources connected.")

    prompt = CLASSIFY_PROMPT.format(
        source_context=source_context,
        question=question,
    )

    try:
        result, usage = await llm.generate_json(
            [Message(role="user", content=prompt)],
            system="You are a query classifier. Respond with JSON only.",
        )

        mode = result.get("mode", "simple")
        if mode not in ("quick", "simple", "extended", "optimization_required", "deep"):
            mode = "simple"

        state["query_mode"] = mode
        state["target_sources"] = result.get("target_sources", state.get("active_source_ids", []))
        state["requires_cross_source"] = result.get("requires_cross_source", False)
        state["key_entities"] = result.get("key_entities", [])

        callbacks.emit(
            "classify/complete",
            mode=mode,
            reasoning=result.get("reasoning", ""),
        )

    except Exception as e:
        logger.warning("Classification failed, defaulting to simple: %s", e)
        state["query_mode"] = "simple"
        state["target_sources"] = state.get("active_source_ids", [])
        state["requires_cross_source"] = False
        state["key_entities"] = []
        callbacks.emit("classify/complete", mode="simple", reasoning="fallback")

    return state
