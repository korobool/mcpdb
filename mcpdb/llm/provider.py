"""LLM provider abstraction."""

from __future__ import annotations

import json
import logging
import re
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


def _repair_json(text: str) -> str:
    """Try to repair truncated or malformed JSON from LLM output.

    Handles common LLM issues:
    - Truncated JSON (unclosed strings, missing braces)
    - Trailing commas before } or ]
    """
    text = text.strip()

    # Remove trailing commas before } or ]
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # If the JSON looks complete, return as-is
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    # Try to close truncated JSON
    # 1. Close any unclosed string
    in_string = False
    escape = False
    for c in text:
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string

    if in_string:
        text += '"'

    # 2. Close unclosed braces/brackets using a stack to preserve correct order
    stack: list[str] = []
    in_str = False
    esc = False
    for c in text:
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            stack.append("}")
        elif c == "[":
            stack.append("]")
        elif c in ("}", "]") and stack and stack[-1] == c:
            stack.pop()

    # Close in reverse order (inner-to-outer)
    text += "".join(reversed(stack))

    # Remove trailing commas again after repair
    text = re.sub(r",\s*([}\]])", r"\1", text)

    return text


def _extract_json(text: str) -> dict:
    """Robustly extract a JSON object from LLM output.

    Handles: raw JSON, markdown code blocks, JSON embedded in text,
    and truncated/malformed JSON from LLM responses.
    """
    text = text.strip()

    # 1. Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Try stripping markdown code block wrappers (```json ... ```)
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if code_block:
        inner = code_block.group(1).strip()
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            # Try repairing the code block content
            try:
                return json.loads(_repair_json(inner))
            except json.JSONDecodeError:
                pass

    # 3. Try extracting the first {...} block via brace matching
    start = text.find("{")
    if start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break

        # 4. Try repairing truncated JSON (e.g., from Gemini thinking token budget)
        try:
            repaired = _repair_json(text[start:])
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError(
        f"Could not extract JSON from LLM response: {text[:200]}",
        text,
        0,
    )


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
        max_tokens: int = 16384,
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
        max_tokens: int = 16384,
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
        max_tokens: int = 16384,
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
        return _extract_json(text), usage


class AnthropicProvider(LLMProvider):
    """Anthropic API provider (Claude Opus, Sonnet, Haiku)."""

    def __init__(self, model: str = "claude-sonnet-4-6", api_key: str = "") -> None:
        self.model = model
        self._api_key = api_key
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise ValueError(
                    "Anthropic API key not set. "
                    "Set ANTHROPIC_API_KEY environment variable or configure "
                    "llm.reasoning.api_key in mcpdb.yaml."
                )
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
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
