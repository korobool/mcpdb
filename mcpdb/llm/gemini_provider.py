"""Google Gemini provider — Gemini models via Google AI API."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from mcpdb.llm.config import TokenUsage
from mcpdb.llm.provider import LLMProvider, Message, StreamChunk

logger = logging.getLogger("mcpdb.llm.gemini")


class GeminiProvider(LLMProvider):
    """LLM provider for Google Gemini models."""

    def __init__(
        self,
        model: str = "gemini-2.0-flash",
        api_key: str = "",
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import google.generativeai as genai
            except ImportError:
                raise ImportError(
                    "Gemini provider requires google-generativeai. "
                    "Install with: pip install google-generativeai"
                )
            if self._api_key:
                genai.configure(api_key=self._api_key)
            self._client = genai.GenerativeModel(self.model)
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

        # Build content list for Gemini
        contents = []
        if system:
            contents.append({"role": "user", "parts": [f"System instruction: {system}"]})
            contents.append({"role": "model", "parts": ["Understood."]})

        for msg in messages:
            role = "model" if msg.role == "assistant" else "user"
            contents.append({"role": role, "parts": [msg.content]})

        try:
            import google.generativeai as genai
            config = genai.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
            )
        except ImportError:
            raise ImportError(
                "Gemini provider requires google-generativeai."
            )

        response = await client.generate_content_async(
            contents,
            generation_config=config,
            stream=True,
        )

        total_tokens = 0
        async for chunk in response:
            if chunk.text:
                yield StreamChunk(text=chunk.text)

        # Usage from response metadata
        usage_meta = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage_meta, "prompt_token_count", 0) if usage_meta else 0
        output_tokens = getattr(usage_meta, "candidates_token_count", 0) if usage_meta else 0

        yield StreamChunk(
            text="",
            usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        )
