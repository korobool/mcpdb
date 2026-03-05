"""OpenAI provider — GPT models via OpenAI API."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from mcpdb.llm.config import TokenUsage
from mcpdb.llm.provider import LLMProvider, Message, StreamChunk

logger = logging.getLogger("mcpdb.llm.openai")


class OpenAIProvider(LLMProvider):
    """LLM provider for OpenAI GPT models."""

    def __init__(
        self,
        model: str = "gpt-4.1",
        api_key: str = "",
        base_url: str | None = None,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._base_url = base_url
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise ValueError(
                    "OpenAI API key not set. "
                    "Set OPENAI_API_KEY environment variable or configure "
                    "llm.reasoning.api_key in mcpdb.yaml."
                )
            try:
                from openai import AsyncOpenAI
            except ImportError:
                raise ImportError(
                    "OpenAI provider requires the openai package. "
                    "Install with: pip install openai"
                )
            kwargs: dict[str, Any] = {"api_key": self._api_key}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    async def stream(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 16384,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        client = self._get_client()

        api_messages: list[dict[str, str]] = []
        if system:
            api_messages.append({"role": "system", "content": system})
        api_messages.extend(
            {"role": m.role, "content": m.content} for m in messages
        )

        stream = await client.chat.completions.create(
            model=self.model,
            messages=api_messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            stream_options={"include_usage": True},
        )

        input_tokens = 0
        output_tokens = 0

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield StreamChunk(text=chunk.choices[0].delta.content)
            if hasattr(chunk, "usage") and chunk.usage:
                input_tokens = getattr(chunk.usage, "prompt_tokens", 0) or 0
                output_tokens = getattr(chunk.usage, "completion_tokens", 0) or 0

        yield StreamChunk(
            text="",
            usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        )
