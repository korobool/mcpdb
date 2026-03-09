"""LLM usage tracking wrapper — intercepts all LLM calls to accumulate token counts."""

from __future__ import annotations

from typing import Any, AsyncIterator

from mcpdb.llm.config import LLMUsage, TokenUsage
from mcpdb.llm.provider import LLMProvider, Message, StreamChunk


def _ensure_token_usage(usage: Any) -> TokenUsage:
    """Coerce a usage value to TokenUsage (handles dicts and missing attrs)."""
    if isinstance(usage, TokenUsage):
        return usage
    if isinstance(usage, dict):
        return TokenUsage(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )
    # Fallback for unknown types
    return TokenUsage(
        input_tokens=getattr(usage, "input_tokens", 0),
        output_tokens=getattr(usage, "output_tokens", 0),
    )


class TrackingLLMProvider(LLMProvider):
    """Transparent wrapper that tracks token usage across all LLM calls.

    Delegates to the underlying provider while accumulating usage metrics
    in an ``LLMUsage`` instance.  Optionally emits ``llm/complete`` callback
    events so the UI can show running totals.
    """

    def __init__(self, inner: LLMProvider, callbacks: Any = None) -> None:
        self._inner = inner
        self._callbacks = callbacks
        self.usage = LLMUsage()

    # Expose model name for downstream code that reads it
    @property
    def model(self) -> str:
        return getattr(self._inner, "model", "unknown")

    @model.setter
    def model(self, value: str) -> None:
        if hasattr(self._inner, "model"):
            self._inner.model = value

    async def stream(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 16384,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Stream from inner provider, capturing usage from the final chunk."""
        usage = TokenUsage()
        async for chunk in self._inner.stream(
            messages,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        ):
            if chunk.usage:
                usage = chunk.usage
            yield chunk

        # Record usage after stream completes
        usage = _ensure_token_usage(usage)
        self.usage.add("stream", usage, model=self.model)
        self._emit(usage)

    async def generate(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 16384,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> tuple[str, TokenUsage]:
        """Generate from inner provider, tracking usage."""
        text, raw_usage = await self._inner.generate(
            messages,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )
        usage = _ensure_token_usage(raw_usage)
        self.usage.add("generate", usage, model=self.model)
        self._emit(usage)
        return text, raw_usage

    async def generate_json(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 16384,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> tuple[dict, TokenUsage]:
        """Generate JSON from inner provider, tracking usage."""
        result, raw_usage = await self._inner.generate_json(
            messages,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )
        usage = _ensure_token_usage(raw_usage)
        self.usage.add("generate_json", usage, model=self.model)
        self._emit(usage)
        return result, raw_usage

    def _emit(self, usage: TokenUsage) -> None:
        """Emit llm/complete callback with per-call and running totals."""
        if self._callbacks is not None:
            self._callbacks.emit(
                "llm/complete",
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_calls=self.usage.calls,
                total_input_tokens=self.usage.input_tokens,
                total_output_tokens=self.usage.output_tokens,
            )
