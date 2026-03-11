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
6. **off_topic** — Question is NOT about the data, database, or domain. Greetings, general chat, trivia, coding help, jokes, philosophy, etc.

Respond with JSON only:
{{"mode": "quick|simple|extended|optimization_required|deep|off_topic", "reasoning": "Why this mode", "target_sources": ["source_id"], "requires_cross_source": false, "key_entities": ["tables/columns mentioned"]}}
"""


import re as _re

# Questions that can be answered from schema context alone — skip LLM classification
_QUICK_PATTERNS = [
    _re.compile(r"\b(mermaid|er\s*diagram|erd|entity.?relation|schema\s*(diagram|graph|visual|plot|draw|chart|map))\b", _re.I),
    _re.compile(r"\b(list|show|what|how many)\b.{0,30}\b(tables?|columns?|schema|fields?|structure)\b", _re.I),
    _re.compile(r"\b(describe|explain)\b.{0,20}\b(schema|structure|tables?)\b", _re.I),
    _re.compile(r"\b(plot|draw|render|generate|create|make)\b.{0,30}\b(schema|erd|diagram|er\b)", _re.I),
    _re.compile(r"\b(foreign\s*keys?|relationships?|primary\s*keys?)\b", _re.I),
]

# Obvious off-topic — pure greetings / chat with no data-related words
_OFF_TOPIC_PATTERNS = [
    _re.compile(r"^(hi|hello|hey|howdy|yo|sup|hola|greetings|good\s*(morning|evening|afternoon|day)|what'?s?\s*up)\s*[!?.]*$", _re.I),
    _re.compile(r"^(who\s+are\s+you|what\s+are\s+you|tell\s+me\s+(about\s+yourself|a\s+joke))\s*[?!.]*$", _re.I),
    _re.compile(r"^(thanks?|thank\s*you|thx|bye|goodbye|see\s*ya|ciao)\s*[!?.]*$", _re.I),
]


def _fast_classify(question: str) -> str | None:
    """Return mode without LLM call for obvious patterns, or None to use LLM."""
    for pat in _QUICK_PATTERNS:
        if pat.search(question):
            return "quick"
    for pat in _OFF_TOPIC_PATTERNS:
        if pat.search(question.strip()):
            return "off_topic"
    return None


async def classify(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> AgentState:
    """Classify a question into a thinking mode."""
    callbacks.emit("classify/start", question=state["question"])

    question = state["question"]
    source_context = state.get("source_context", "No sources connected.")

    # Fast path: skip LLM for obvious schema/metadata questions
    fast_mode = _fast_classify(question)
    if fast_mode:
        state["query_mode"] = fast_mode
        state["target_sources"] = state.get("active_source_ids", [])
        state["requires_cross_source"] = False
        state["key_entities"] = []
        callbacks.emit("classify/complete", mode=fast_mode, reasoning="fast-path pattern match")
        return state

    prompt = CLASSIFY_PROMPT.format(
        source_context=source_context,
        question=question,
    )

    import asyncio
    for retry in range(3):
        try:
            result, usage = await asyncio.wait_for(
                llm.generate_json(
                    [Message(role="user", content=prompt)],
                    system="You are a query classifier. Respond with JSON only.",
                ),
                timeout=30.0,
            )

            mode = result.get("mode", "simple")
            if mode not in ("quick", "simple", "extended", "optimization_required", "deep", "sequential", "off_topic"):
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
            return state

        except asyncio.TimeoutError:
            logger.warning("Classification timed out (retry %d)", retry + 1)
        except Exception as e:
            if retry < 2:
                delay = [2, 5][min(retry, 1)]
                logger.warning("Classification failed (retry %d), retrying in %ds: %s", retry + 1, delay, e)
                await asyncio.sleep(delay)
            else:
                logger.warning("Classification failed, defaulting to simple: %s", e)
                state["query_mode"] = "simple"
                state["target_sources"] = state.get("active_source_ids", [])
                state["requires_cross_source"] = False
                state["key_entities"] = []
                callbacks.emit("classify/complete", mode="simple", reasoning="fallback")

    return state
