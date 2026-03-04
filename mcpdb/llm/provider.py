"""LLM provider abstraction and Anthropic implementation."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator

from mcpdb.llm.config import TokenUsage

logger = logging.getLogger("mcpdb.llm")


@dataclass
class StreamChunk:
    """A chunk from an LLM streaming response."""

    text: str
    usage: TokenUsage | None = None  # Only set on the final chunk


@dataclass
class Message:
    """Simple message type for LLM calls."""

    role: str  # "user", "assistant", "system"
    content: str


class LLMProvider(ABC):
    """Abstract LLM provider interface.

    All methods are async. Streaming is the primary interface.
    """

    @abstractmethod
    async def stream(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming call. Yields StreamChunk for each token batch."""
        ...

    async def generate(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> tuple[str, TokenUsage]:
        """Non-streaming call. Collects stream into full response."""
        chunks: list[str] = []
        usage = TokenUsage()
        async for chunk in self.stream(
            messages,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        ):
            chunks.append(chunk.text)
            if chunk.usage:
                usage = chunk.usage
        return "".join(chunks), usage

    async def generate_json(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> tuple[dict, TokenUsage]:
        """Generate structured JSON output."""
        text, usage = await self.generate(
            messages,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )
        # Extract JSON from response (handle markdown code blocks)
        text = text.strip()
        if text.startswith("```"):
            # Remove ```json ... ``` wrapper
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(text), usage


class AnthropicProvider(LLMProvider):
    """Claude via Anthropic API."""

    def __init__(self, model: str = "claude-sonnet-4-6", api_key: str = "") -> None:
        self.model = model
        self._api_key = api_key
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic
            kwargs: dict[str, Any] = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            self._client = anthropic.AsyncAnthropic(**kwargs)
        return self._client

    async def stream(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        client = self._get_client()

        api_messages = [{"role": m.role, "content": m.content} for m in messages]

        api_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            api_kwargs["system"] = system

        async with client.messages.stream(**api_kwargs) as stream:
            async for text in stream.text_stream:
                yield StreamChunk(text=text)

            # Final chunk with usage
            response = await stream.get_final_message()
            yield StreamChunk(
                text="",
                usage=TokenUsage(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                ),
            )
