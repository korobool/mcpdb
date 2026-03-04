"""Tests for v0.0.3 — LLM provider interface."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import pytest

from mcpdb.llm.config import LLMUsage, ModelConfig, TokenUsage
from mcpdb.llm.provider import (
    AnthropicProvider,
    LLMProvider,
    Message,
    StreamChunk,
)


# --- Mock provider for testing ---


class MockProvider(LLMProvider):
    """Deterministic provider that yields pre-configured responses."""

    def __init__(self, response_text: str = "Hello, world!"):
        self.response_text = response_text
        self.last_messages: list[Message] = []
        self.last_system: str | None = None

    async def stream(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        self.last_messages = messages
        self.last_system = system
        # Simulate streaming: yield word by word
        words = self.response_text.split(" ")
        for i, word in enumerate(words):
            text = word if i == 0 else " " + word
            yield StreamChunk(text=text)
        # Final chunk with usage
        yield StreamChunk(
            text="",
            usage=TokenUsage(input_tokens=10, output_tokens=len(words)),
        )


# --- Tests ---


class TestModelConfig:
    def test_defaults(self):
        cfg = ModelConfig()
        assert cfg.reasoning_provider == "anthropic"
        assert cfg.reasoning_model == "claude-sonnet-4-6"
        assert cfg.fast_model == "claude-haiku-4-5-20251001"
        assert cfg.temperature == 0.0
        assert cfg.max_tokens == 4096

    def test_custom(self):
        cfg = ModelConfig(reasoning_provider="openai", reasoning_model="gpt-4o")
        assert cfg.reasoning_provider == "openai"


class TestTokenUsage:
    def test_defaults(self):
        u = TokenUsage()
        assert u.input_tokens == 0
        assert u.output_tokens == 0


class TestLLMUsage:
    def test_add(self):
        usage = LLMUsage()
        usage.add("plan", TokenUsage(input_tokens=100, output_tokens=50), model="claude-sonnet-4-6")
        usage.add("synthesize", TokenUsage(input_tokens=200, output_tokens=30), model="claude-haiku-4-5-20251001")
        assert usage.calls == 2
        assert usage.input_tokens == 300
        assert usage.output_tokens == 80
        assert len(usage.breakdown) == 2


class TestStreamChunk:
    def test_basic(self):
        chunk = StreamChunk(text="hello")
        assert chunk.text == "hello"
        assert chunk.usage is None

    def test_with_usage(self):
        chunk = StreamChunk(text="", usage=TokenUsage(10, 20))
        assert chunk.usage is not None
        assert chunk.usage.input_tokens == 10


class TestMessage:
    def test_create(self):
        msg = Message(role="user", content="hi")
        assert msg.role == "user"
        assert msg.content == "hi"


class TestMockProvider:
    @pytest.mark.asyncio
    async def test_stream(self):
        provider = MockProvider("Hello world")
        chunks = []
        async for chunk in provider.stream([Message(role="user", content="test")]):
            chunks.append(chunk)
        # "Hello" + " world" + final empty
        assert len(chunks) == 3
        assert chunks[0].text == "Hello"
        assert chunks[1].text == " world"
        assert chunks[2].text == ""
        assert chunks[2].usage is not None
        assert chunks[2].usage.input_tokens == 10

    @pytest.mark.asyncio
    async def test_generate(self):
        provider = MockProvider("The answer is 42")
        text, usage = await provider.generate([Message(role="user", content="test")])
        assert text == "The answer is 42"
        assert usage.input_tokens == 10
        assert usage.output_tokens == 4

    @pytest.mark.asyncio
    async def test_generate_json(self):
        provider = MockProvider('```json\n{"key": "value"}\n```')
        result, usage = await provider.generate_json(
            [Message(role="user", content="give me json")]
        )
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_generate_json_no_wrapper(self):
        provider = MockProvider('{"key": "value"}')
        result, usage = await provider.generate_json(
            [Message(role="user", content="give me json")]
        )
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_system_prompt_passed(self):
        provider = MockProvider("ok")
        await provider.generate(
            [Message(role="user", content="test")],
            system="You are helpful.",
        )
        assert provider.last_system == "You are helpful."


class TestAnthropicProvider:
    def test_instantiation(self):
        provider = AnthropicProvider(model="claude-sonnet-4-6", api_key="sk-test")
        assert provider.model == "claude-sonnet-4-6"

    def test_default_model(self):
        provider = AnthropicProvider()
        assert provider.model == "claude-sonnet-4-6"

    def test_lazy_client(self):
        provider = AnthropicProvider(api_key="sk-test")
        # Client not created until first use
        assert provider._client is None
