"""Classify node — routes questions to the appropriate thinking mode."""

from __future__ import annotations

import asyncio
import logging
import re as _re
from typing import Any

from mcpdb.agent.state import AgentState, ALL_MODES
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.llm.provider import LLMProvider, Message

logger = logging.getLogger("mcpdb.agent.classify")

# ── Full classify prompt (all modes) ─────────────────────────────

CLASSIFY_PROMPT = """\
You are a query classifier for a multi-source data assistant.

ACTIVE DATA SOURCES:
{source_context}

USER QUESTION: {question}

AVAILABLE MODES:
{modes_section}

IMPORTANT: "quick" is ONLY for questions answerable from schema/metadata or prior conversation context (e.g. table names, column types, ERD, clarifying a previous result). Any question that requires new data queries, counting, computing, calculating, or analyzing actual data MUST use "simple" or higher — never "quick". When in doubt, prefer "simple".

Respond with JSON only:
{{"mode": "{valid_modes_str}", "reasoning": "Why this mode", "target_sources": ["source_id"], "requires_cross_source": false, "key_entities": ["tables/columns mentioned"]}}
"""

_MODE_DESCRIPTIONS = {
    "quick": "ONLY for questions answerable from schema/metadata or prior conversation context (e.g. schema lookup, summarize/reason about previous results). Never for questions requiring new data queries or computation",
    "simple": "1-5 execution steps (DEFAULT for most data questions)",
    "extended": "3-10 steps for comprehensive analysis, EDA, root cause",
    "optimization_required": "Large table operations (>1M rows, no narrow filters)",
    "deep": "Multi-investigation research (e.g., \"investigate customer churn\", \"comprehensive audit\")",
    "off_topic": "Question is NOT about the data, database, or domain. Greetings, general chat, trivia, coding help, jokes, philosophy, etc.",
}

# ── Fast-path patterns ───────────────────────────────────────────

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


def _build_modes_section(allowed_modes: frozenset[str]) -> tuple[str, str]:
    """Build the AVAILABLE MODES section and valid_modes_str for the prompt.

    Returns (modes_section, valid_modes_str).
    """
    lines = []
    valid = []
    for i, (mode, desc) in enumerate(_MODE_DESCRIPTIONS.items(), 1):
        if mode in allowed_modes:
            lines.append(f"{i}. **{mode}** — {desc}")
            valid.append(mode)
    return "\n".join(lines), "|".join(valid)


# ── Core classifier (reusable) ───────────────────────────────────

async def classify_question(
    question: str,
    source_context: str,
    llm: LLMProvider,
    allowed_modes: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Classify a question into a mode. Standalone — no AgentState needed.

    Args:
        question: The user question to classify.
        source_context: Schema/source information string.
        llm: LLM provider for classification.
        allowed_modes: If set, restrict output to these modes only.
            Used by metamodes to prevent recursive metamode classification.

    Returns:
        Dict with mode, reasoning, target_sources, requires_cross_source, key_entities.
    """
    if allowed_modes is None:
        allowed_modes = ALL_MODES

    default_mode = "simple" if "simple" in allowed_modes else next(iter(allowed_modes))

    # Fast path (only if the result is in the allowed set)
    fast_mode = _fast_classify(question)
    if fast_mode and fast_mode in allowed_modes:
        return {
            "mode": fast_mode,
            "reasoning": "fast-path pattern match",
            "target_sources": [],
            "requires_cross_source": False,
            "key_entities": [],
        }

    modes_section, valid_modes_str = _build_modes_section(allowed_modes)
    prompt = CLASSIFY_PROMPT.format(
        source_context=source_context,
        question=question,
        modes_section=modes_section,
        valid_modes_str=valid_modes_str,
    )

    for retry in range(3):
        try:
            result, usage = await asyncio.wait_for(
                llm.generate_json(
                    [Message(role="user", content=prompt)],
                    system="You are a query classifier. Respond with JSON only.",
                ),
                timeout=30.0,
            )

            mode = result.get("mode", default_mode)
            if mode not in allowed_modes:
                mode = default_mode

            return {
                "mode": mode,
                "reasoning": result.get("reasoning", ""),
                "target_sources": result.get("target_sources", []),
                "requires_cross_source": result.get("requires_cross_source", False),
                "key_entities": result.get("key_entities", []),
            }

        except asyncio.TimeoutError:
            logger.warning("Classification timed out (retry %d)", retry + 1)
        except Exception as e:
            if retry < 2:
                delay = [2, 5][min(retry, 1)]
                logger.warning("Classification failed (retry %d), retrying in %ds: %s", retry + 1, delay, e)
                await asyncio.sleep(delay)
            else:
                logger.warning("Classification failed, defaulting to %s: %s", default_mode, e)

    return {
        "mode": default_mode,
        "reasoning": "fallback",
        "target_sources": [],
        "requires_cross_source": False,
        "key_entities": [],
    }


# ── Graph node (wraps classify_question for AgentState) ──────────

async def classify(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> AgentState:
    """Classify a question into a thinking mode (graph node)."""
    callbacks.emit("classify/start", question=state["question"])

    result = await classify_question(
        question=state["question"],
        source_context=state.get("source_context", "No sources connected."),
        llm=llm,
    )

    state["query_mode"] = result["mode"]
    state["target_sources"] = result["target_sources"] or state.get("active_source_ids", [])
    state["requires_cross_source"] = result["requires_cross_source"]
    state["key_entities"] = result["key_entities"]

    callbacks.emit("classify/complete", mode=result["mode"], reasoning=result["reasoning"])
    return state
