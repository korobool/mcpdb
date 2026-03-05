"""Ollama provider — local models via Ollama API."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from mcpdb.llm.config import TokenUsage
from mcpdb.llm.provider import LLMProvider, Message, StreamChunk

logger = logging.getLogger("mcpdb.llm.ollama")


class OllamaProvider(LLMProvider):
    """LLM provider for local models via Ollama."""

    def __init__(
        self,
        model: str = "llama3.1",
        base_url: str = "http://localhost:11434",
    ) -> None:
        self.model = model
        self._base_url = base_url.rstrip("/")

    async def stream(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 16384,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        try:
            import httpx
        except ImportError:
            raise ImportError(
                "Ollama provider requires httpx. Install with: pip install httpx"
            )

        api_messages: list[dict[str, str]] = []
        if system:
            api_messages.append({"role": "system", "content": system})
        api_messages.extend(
            {"role": m.role, "content": m.content} for m in messages
        )

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": api_messages,
                    "stream": True,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                    },
                },
            ) as response:
                response.raise_for_status()
                total_eval = 0
                total_prompt = 0

                import json as json_mod
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json_mod.loads(line)
                    except Exception:
                        continue

                    if "message" in data and data["message"].get("content"):
                        yield StreamChunk(text=data["message"]["content"])

                    if data.get("done"):
                        total_eval = data.get("eval_count", 0)
                        total_prompt = data.get("prompt_eval_count", 0)

                yield StreamChunk(
                    text="",
                    usage=TokenUsage(
                        input_tokens=total_prompt,
                        output_tokens=total_eval,
                    ),
                )
