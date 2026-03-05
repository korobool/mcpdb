"""Google Gemini provider — Gemini models via the google-genai SDK."""

from __future__ import annotations

import logging
import warnings
from typing import Any, AsyncIterator

# Suppress FutureWarning if old google-generativeai package is co-installed
warnings.filterwarnings("ignore", message=".*google.generativeai.*")

from mcpdb.llm.config import TokenUsage
from mcpdb.llm.provider import LLMProvider, Message, StreamChunk

logger = logging.getLogger("mcpdb.llm.gemini")


class GeminiProvider(LLMProvider):
    """LLM provider for Google Gemini models using the google-genai SDK."""

    def __init__(
        self,
        model: str = "gemini-2.5-pro",
        api_key: str = "",
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise ValueError(
                    "Gemini API key not set. "
                    "Set GEMINI_API_KEY environment variable or configure "
                    "llm.reasoning.api_key in mcpdb.yaml."
                )
            try:
                from google import genai
            except ImportError:
                raise ImportError(
                    "Gemini provider requires google-genai. "
                    "Install with: pip install google-genai"
                )
            self._client = genai.Client(api_key=self._api_key)
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

        try:
            from google.genai import types
        except ImportError:
            raise ImportError("Gemini provider requires google-genai.")

        # Build contents list
        contents = []
        for msg in messages:
            role = "model" if msg.role == "assistant" else "user"
            contents.append(types.Content(
                role=role,
                parts=[types.Part(text=msg.content)],
            ))

        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            temperature=temperature,
        )

        response = await client.aio.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=config,
        )

        input_tokens = 0
        output_tokens = 0

        async for chunk in response:
            text = chunk.text if chunk.text else None
            if text:
                yield StreamChunk(text=text)

            # Capture usage from the last chunk
            usage_meta = getattr(chunk, "usage_metadata", None)
            if usage_meta:
                input_tokens = getattr(usage_meta, "prompt_token_count", 0) or 0
                output_tokens = getattr(usage_meta, "candidates_token_count", 0) or 0

        yield StreamChunk(
            text="",
            usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        )
