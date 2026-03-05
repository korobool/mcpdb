"""Quick mode subgraph — answer from context only, no code execution."""

from __future__ import annotations

import logging
from typing import Any

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.llm.provider import LLMProvider, Message

logger = logging.getLogger("mcpdb.agent.quick")

CONTEXT_ANSWER_PROMPT = """\
You are a data assistant. Answer the user's question using ONLY the schema context below.
Do NOT make up data values. If you need actual data to answer, respond with:
{{"action": "escalate", "reason": "needs data values"}}

Otherwise respond with:
{{"action": "answer", "text": "Your answer here"}}

IMPORTANT RULES:
- When the user asks to LIST items (tables, columns, etc.), you MUST include EVERY single item. Never summarize, truncate, or say "and N more". List them ALL.
- Use markdown formatting (bullet lists, tables) for readability.

SCHEMA CONTEXT:
{source_context}

USER QUESTION: {question}

Respond with JSON only.
"""


async def run_quick(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> AgentState:
    """Execute the Quick mode subgraph.

    1. context_answer: Answer from schema context
    2. If escalation needed: set validation_result = "needs_data"
    """
    callbacks.emit("quick/start")

    question = state["question"]
    source_context = state.get("source_context", "No sources connected.")

    prompt = CONTEXT_ANSWER_PROMPT.format(
        source_context=source_context,
        question=question,
    )

    try:
        result, usage = await llm.generate_json(
            [Message(role="user", content=prompt)],
            system="You are a data assistant. Respond with JSON only.",
        )

        action = result.get("action", "answer")
        text = result.get("text", "")

        if action == "escalate" or not text:
            # Escalate if LLM says so, or if response is empty
            state["validation_result"] = "needs_data"
            state["query_mode"] = "simple"
            reason = result.get("reason", "needs data") if action == "escalate" else "empty response"
            callbacks.emit(
                "quick/escalate",
                reason=reason,
            )
        else:
            state["response"] = text
            state["validation_result"] = "complete"
            callbacks.emit("quick/complete")

    except Exception as e:
        logger.warning("Quick mode failed, escalating: %s", e)
        state["validation_result"] = "needs_data"
        state["query_mode"] = "simple"
        callbacks.emit("quick/escalate", reason=f"error: {e}")

    return state
