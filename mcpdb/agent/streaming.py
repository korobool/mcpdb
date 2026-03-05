"""LLM streaming wrapper with event emission and cancellation support."""

from __future__ import annotations

import logging
from typing import Any

from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.cancellation import CancellationToken
from mcpdb.llm.provider import LLMProvider, Message, StreamChunk, _extract_json
from mcpdb.llm.config import TokenUsage

logger = logging.getLogger("mcpdb.agent.streaming")


async def stream_llm_call(
    llm: LLMProvider,
    messages: list[Message],
    callbacks: CallbackManager,
    *,
    system: str | None = None,
    max_tokens: int = 16384,
    temperature: float = 0.0,
    label: str = "llm",
    cancellation: CancellationToken | None = None,
    **kwargs: Any,
) -> tuple[str, TokenUsage]:
    """Stream an LLM call with event emission and cancellation checks.

    Emits:
        llm/start — when the call begins
        llm/token — for each token batch (with text and accumulated text)
        llm/complete — when done (with full text and usage)

    Returns:
        (full_text, usage) tuple
    """
    callbacks.emit("llm/start", label=label, max_tokens=max_tokens)

    if cancellation:
        cancellation.check()

    chunks: list[str] = []
    usage = TokenUsage()

    async for chunk in llm.stream(
        messages,
        system=system,
        max_tokens=max_tokens,
        temperature=temperature,
        **kwargs,
    ):
        if chunk.text:
            chunks.append(chunk.text)
            callbacks.emit(
                "llm/token",
                label=label,
                text=chunk.text,
                accumulated_length=sum(len(c) for c in chunks),
            )

        if chunk.usage:
            usage = chunk.usage

        # Check cancellation between token chunks
        if cancellation and cancellation.is_cancelled:
            callbacks.emit("llm/cancelled", label=label, partial_length=sum(len(c) for c in chunks))
            from mcpdb.agent.cancellation import CancelledException
            raise CancelledException("LLM call cancelled")

    full_text = "".join(chunks)
    callbacks.emit(
        "llm/complete",
        label=label,
        length=len(full_text),
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )
    return full_text, usage


async def stream_llm_json(
    llm: LLMProvider,
    messages: list[Message],
    callbacks: CallbackManager,
    *,
    system: str | None = None,
    max_tokens: int = 16384,
    temperature: float = 0.0,
    label: str = "llm",
    cancellation: CancellationToken | None = None,
    **kwargs: Any,
) -> tuple[dict, TokenUsage]:
    """Stream an LLM call and parse the result as JSON.

    Same as stream_llm_call but parses the output as JSON.
    """
    text, usage = await stream_llm_call(
        llm, messages, callbacks,
        system=system, max_tokens=max_tokens, temperature=temperature,
        label=label, cancellation=cancellation, **kwargs,
    )

    return _extract_json(text), usage
