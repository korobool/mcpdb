"""Provider factory and fallback chain."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from mcpdb.llm.config import TokenUsage
from mcpdb.llm.provider import LLMProvider, Message, StreamChunk

logger = logging.getLogger("mcpdb.llm.factory")


def create_provider(
    provider_name: str,
    model: str = "",
    api_key: str = "",
    **kwargs: Any,
) -> LLMProvider:
    """Create an LLM provider by name.

    Supported providers: anthropic, openai, gemini, ollama.
    """
    name = provider_name.lower()

    if name == "anthropic":
        from mcpdb.llm.provider import AnthropicProvider
        return AnthropicProvider(
            model=model or "claude-sonnet-4-6",
            api_key=api_key,
        )
    elif name == "openai":
        from mcpdb.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(
            model=model or "gpt-4o",
            api_key=api_key,
            base_url=kwargs.get("base_url"),
        )
    elif name == "gemini":
        from mcpdb.llm.gemini_provider import GeminiProvider
        return GeminiProvider(
            model=model or "gemini-2.0-flash",
            api_key=api_key,
        )
    elif name == "ollama":
        from mcpdb.llm.ollama_provider import OllamaProvider
        return OllamaProvider(
            model=model or "llama3.1",
            base_url=kwargs.get("base_url", "http://localhost:11434"),
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}")


class FallbackProvider(LLMProvider):
    """Provider that tries multiple providers in sequence.

    If the primary fails, falls back to secondary, then fast.
    """

    def __init__(self, providers: list[LLMProvider]) -> None:
        if not providers:
            raise ValueError("At least one provider is required")
        self._providers = providers

    async def stream(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        last_error: Exception | None = None

        for i, provider in enumerate(self._providers):
            try:
                async for chunk in provider.stream(
                    messages,
                    system=system,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    **kwargs,
                ):
                    yield chunk
                return  # Success
            except Exception as e:
                last_error = e
                provider_name = type(provider).__name__
                logger.warning(
                    "Provider %s (%d/%d) failed: %s. Trying next...",
                    provider_name,
                    i + 1,
                    len(self._providers),
                    e,
                )

        if last_error:
            raise last_error

    @property
    def providers(self) -> list[LLMProvider]:
        return list(self._providers)
