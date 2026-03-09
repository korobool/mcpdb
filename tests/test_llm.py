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
    _extract_json,
    _repair_json,
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
        assert cfg.reasoning_provider == "gemini"
        assert cfg.reasoning_model == "gemini-2.5-pro"
        assert cfg.fast_model == "gemini-2.5-flash"
        assert cfg.temperature == 0.0
        assert cfg.max_tokens == 16384

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
        usage.add("plan", TokenUsage(input_tokens=100, output_tokens=50), model="gemini-2.5-pro")
        usage.add("synthesize", TokenUsage(input_tokens=200, output_tokens=30), model="gemini-2.5-flash")
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


class TestExtractJson:
    """Tests for the robust JSON extraction helper."""

    def test_plain_json(self):
        assert _extract_json('{"key": "value"}') == {"key": "value"}

    def test_markdown_code_block(self):
        assert _extract_json('```json\n{"key": "value"}\n```') == {"key": "value"}

    def test_code_block_no_lang(self):
        assert _extract_json('```\n{"key": 1}\n```') == {"key": 1}

    def test_json_with_surrounding_text(self):
        text = 'Here is the plan:\n{"mode": "simple", "steps": []}\nDone.'
        assert _extract_json(text) == {"mode": "simple", "steps": []}

    def test_json_with_leading_text(self):
        text = 'Sure, here is the JSON response:\n{"analysis": "test"}'
        assert _extract_json(text) == {"analysis": "test"}

    def test_nested_json(self):
        text = '{"outer": {"inner": "value"}, "list": [1, 2]}'
        result = _extract_json(text)
        assert result["outer"]["inner"] == "value"
        assert result["list"] == [1, 2]

    def test_json_with_strings_containing_braces(self):
        text = '{"code": "SELECT * FROM t WHERE x IN {1,2}"}'
        result = _extract_json(text)
        assert "SELECT" in result["code"]

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _extract_json("this has no json at all")

    def test_whitespace_padding(self):
        assert _extract_json('  \n  {"a": 1}  \n  ') == {"a": 1}

    def test_truncated_json_repair(self):
        """Gemini thinking tokens can cause truncated JSON responses."""
        text = '{"action": "continue", "reason": "The analysis has completed 3 of 5'
        result = _extract_json(text)
        assert result["action"] == "continue"

    def test_truncated_json_in_code_block(self):
        text = '```json\n{"action": "continue", "reason": "partial\n```'
        result = _extract_json(text)
        assert result["action"] == "continue"

    def test_trailing_comma_repair(self):
        text = '{"steps": [1, 2, 3,], "mode": "simple",}'
        result = _extract_json(text)
        assert result["steps"] == [1, 2, 3]

    def test_truncated_nested_json(self):
        text = '{"analysis": "test", "steps": [{"step": 1, "code": "SELECT'
        result = _extract_json(text)
        assert result["analysis"] == "test"


class TestRepairJson:
    def test_valid_json_unchanged(self):
        text = '{"key": "value"}'
        assert json.loads(_repair_json(text)) == {"key": "value"}

    def test_unclosed_string(self):
        text = '{"key": "val'
        repaired = _repair_json(text)
        result = json.loads(repaired)
        assert result["key"] == "val"

    def test_unclosed_brace(self):
        text = '{"key": "value"'
        repaired = _repair_json(text)
        result = json.loads(repaired)
        assert result["key"] == "value"

    def test_unclosed_array(self):
        text = '{"items": [1, 2, 3'
        repaired = _repair_json(text)
        result = json.loads(repaired)
        assert result["items"] == [1, 2, 3]

    def test_trailing_comma(self):
        text = '{"a": 1, "b": 2,}'
        repaired = _repair_json(text)
        result = json.loads(repaired)
        assert result == {"a": 1, "b": 2}


class TestAnthropicProvider:
    def test_instantiation(self):
        provider = AnthropicProvider(model="claude-sonnet-4-6", api_key="sk-test")
        assert provider.model == "claude-sonnet-4-6"

    def test_default_model(self):
        provider = AnthropicProvider()
        assert provider.model == "claude-sonnet-4-6"

    def test_lazy_client(self):
        provider = AnthropicProvider(api_key="sk-test")
        assert provider._client is None

    def test_top_models(self):
        for model in ("claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"):
            p = AnthropicProvider(model=model, api_key="sk-test")
            assert p.model == model
