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
            max_tokens=2048,
        )

        action = result.get("action", "answer")

        if action == "escalate":
            state["validation_result"] = "needs_data"
            state["query_mode"] = "simple"
            callbacks.emit(
                "quick/escalate",
                reason=result.get("reason", "needs data"),
            )
        else:
            state["response"] = result.get("text", str(result))
            state["validation_result"] = "complete"
            callbacks.emit("quick/complete")

    except Exception as e:
        logger.warning("Quick mode failed, escalating: %s", e)
        state["validation_result"] = "needs_data"
        state["query_mode"] = "simple"
        callbacks.emit("quick/escalate", reason=f"error: {e}")

    return state
