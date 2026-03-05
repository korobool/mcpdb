"""Tests for v3.6.x — Multi-Provider LLM."""

from __future__ import annotations

import asyncio
import pytest

from mcpdb.llm.config import TokenUsage
from mcpdb.llm.provider import LLMProvider, Message, StreamChunk, AnthropicProvider
from mcpdb.llm.factory import create_provider, FallbackProvider


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

class TestCreateProvider:
    def test_anthropic(self):
        p = create_provider("anthropic")
        assert isinstance(p, AnthropicProvider)

    def test_anthropic_custom_model(self):
        p = create_provider("anthropic", model="claude-haiku-4-5-20251001")
        assert p.model == "claude-haiku-4-5-20251001"

    def test_openai(self):
        from mcpdb.llm.openai_provider import OpenAIProvider
        p = create_provider("openai")
        assert isinstance(p, OpenAIProvider)
        assert p.model == "gpt-4.1"

    def test_openai_custom(self):
        from mcpdb.llm.openai_provider import OpenAIProvider
        p = create_provider("openai", model="gpt-4-turbo", api_key="sk-test")
        assert p.model == "gpt-4-turbo"
        assert p._api_key == "sk-test"

    def test_gemini(self):
        from mcpdb.llm.gemini_provider import GeminiProvider
        p = create_provider("gemini")
        assert isinstance(p, GeminiProvider)
        assert p.model == "gemini-2.5-pro"

    def test_ollama(self):
        from mcpdb.llm.ollama_provider import OllamaProvider
        p = create_provider("ollama")
        assert isinstance(p, OllamaProvider)
        assert p.model == "llama3.1"

    def test_ollama_custom_url(self):
        from mcpdb.llm.ollama_provider import OllamaProvider
        p = create_provider("ollama", base_url="http://gpu:11434")
        assert p._base_url == "http://gpu:11434"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown"):
            create_provider("unknown_provider")

    def test_case_insensitive(self):
        p = create_provider("ANTHROPIC")
        assert isinstance(p, AnthropicProvider)


# ---------------------------------------------------------------------------
# FallbackProvider
# ---------------------------------------------------------------------------

class _MockProvider(LLMProvider):
    """Mock provider for testing."""

    def __init__(self, responses: list[str] | None = None, fail: bool = False) -> None:
        self._responses = responses or ["Hello"]
        self._fail = fail
        self.call_count = 0

    async def stream(self, messages, *, system=None, max_tokens=4096,
                     temperature=0.0, **kwargs):
        self.call_count += 1
        if self._fail:
            raise ConnectionError("Provider unavailable")
        for text in self._responses:
            yield StreamChunk(text=text)
        yield StreamChunk(text="", usage=TokenUsage(input_tokens=10, output_tokens=5))


class TestFallbackProvider:
    def test_empty_raises(self):
        with pytest.raises(ValueError):
            FallbackProvider([])

    def test_single_provider(self):
        mock = _MockProvider(["response"])
        fb = FallbackProvider([mock])

        async def run():
            chunks = []
            async for chunk in fb.stream([Message(role="user", content="test")]):
                chunks.append(chunk.text)
            return chunks

        chunks = asyncio.get_event_loop().run_until_complete(run())
        assert "response" in chunks
        assert mock.call_count == 1

    def test_fallback_on_failure(self):
        primary = _MockProvider(fail=True)
        secondary = _MockProvider(["fallback"])
        fb = FallbackProvider([primary, secondary])

        async def run():
            chunks = []
            async for chunk in fb.stream([Message(role="user", content="test")]):
                chunks.append(chunk.text)
            return chunks

        chunks = asyncio.get_event_loop().run_until_complete(run())
        assert "fallback" in chunks
        assert primary.call_count == 1
        assert secondary.call_count == 1

    def test_all_fail_raises(self):
        p1 = _MockProvider(fail=True)
        p2 = _MockProvider(fail=True)
        fb = FallbackProvider([p1, p2])

        async def run():
            chunks = []
            async for chunk in fb.stream([Message(role="user", content="test")]):
                chunks.append(chunk)

        with pytest.raises(ConnectionError):
            asyncio.get_event_loop().run_until_complete(run())

    def test_providers_property(self):
        m1 = _MockProvider()
        m2 = _MockProvider()
        fb = FallbackProvider([m1, m2])
        assert len(fb.providers) == 2

    def test_generate(self):
        mock = _MockProvider(["Hello ", "World"])
        fb = FallbackProvider([mock])

        async def run():
            return await fb.generate([Message(role="user", content="test")])

        text, usage = asyncio.get_event_loop().run_until_complete(run())
        assert "Hello " in text
        assert "World" in text


# ---------------------------------------------------------------------------
# Provider import tests
# ---------------------------------------------------------------------------

class TestImports:
    def test_import_openai_provider(self):
        from mcpdb.llm.openai_provider import OpenAIProvider
        assert callable(OpenAIProvider)

    def test_import_gemini_provider(self):
        from mcpdb.llm.gemini_provider import GeminiProvider
        assert callable(GeminiProvider)

    def test_import_ollama_provider(self):
        from mcpdb.llm.ollama_provider import OllamaProvider
        assert callable(OllamaProvider)

    def test_import_factory(self):
        from mcpdb.llm.factory import create_provider, FallbackProvider
        assert callable(create_provider)
        assert callable(FallbackProvider)

    def test_anthropic_provider_model(self):
        p = AnthropicProvider(model="claude-opus-4-6")
        assert p.model == "claude-opus-4-6"
