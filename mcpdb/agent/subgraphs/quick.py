"""Quick mode subgraph — answer from context only, no code execution."""

from __future__ import annotations

import logging
from typing import Any

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.llm.provider import LLMProvider, Message

logger = logging.getLogger("mcpdb.agent.quick")

CONTEXT_ANSWER_PROMPT = """\
You are a data assistant. Answer the user's question using ONLY the context below.
Do NOT make up data values. If you cannot answer without running queries, reply with exactly: ESCALATE

IMPORTANT RULES:
- When the user asks to LIST items (tables, columns, etc.), you MUST include EVERY single item. Never summarize, truncate, or say "and N more". List them ALL.
- Use markdown formatting (bullet lists, tables, code blocks) for readability.
- For mermaid diagrams, output a fenced ```mermaid code block.
- You may reason about, summarize, or reframe information from PRIOR CONTEXT if available.

SCHEMA CONTEXT:
{source_context}
{prior_context_section}
USER QUESTION: {question}
"""


async def run_quick(
    state: AgentState,
    llm: LLMProvider,
    callbacks: CallbackManager,
) -> AgentState:
    """Execute the Quick mode subgraph.

    1. context_answer: Answer from schema + prior context (direct text, no JSON)
    2. If escalation needed: set validation_result = "needs_data"
    """
    callbacks.emit("quick/start")

    question = state["question"]
    source_context = state.get("source_context", "No sources connected.")

    # Include prior Q&A context if available (from sequential mode, knowledge, etc.)
    knowledge_ctx = state.get("knowledge_context") or ""
    prior_section = f"\nPRIOR CONTEXT:\n{knowledge_ctx}\n" if knowledge_ctx else ""

    prompt = CONTEXT_ANSWER_PROMPT.format(
        source_context=source_context,
        prior_context_section=prior_section,
        question=question,
    )

    try:
        text, usage = await llm.generate(
            [Message(role="user", content=prompt)],
            system="You are a data assistant. Answer directly in markdown.",
        )

        text = text.strip()

        if not text or text == "ESCALATE":
            state["validation_result"] = "needs_data"
            state["query_mode"] = "simple"
            callbacks.emit("quick/escalate", reason="needs data")
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
