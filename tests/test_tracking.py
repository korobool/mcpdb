"""Tests for TrackingLLMProvider token usage tracking."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator
from unittest.mock import MagicMock

import pytest

from mcpdb.agent.tracking import TrackingLLMProvider
from mcpdb.llm.config import TokenUsage
from mcpdb.llm.provider import LLMProvider, Message, StreamChunk


class MockProvider(LLMProvider):
    """Mock LLM provider that returns preset responses with token counts."""

    def __init__(self, input_tokens: int = 100, output_tokens: int = 50) -> None:
        self.model = "mock-model"
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self.call_count = 0

    async def stream(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 16384,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        self.call_count += 1
        yield StreamChunk(text="Hello ")
        yield StreamChunk(text="world")
        yield StreamChunk(
            text="",
            usage=TokenUsage(
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
            ),
        )


class TestTrackingLLMProvider:
    @pytest.mark.asyncio
    async def test_generate_tracks_usage(self):
        mock = MockProvider(input_tokens=100, output_tokens=50)
        tracker = TrackingLLMProvider(mock)

        text, usage = await tracker.generate([Message(role="user", content="hi")])

        assert text == "Hello world"
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert tracker.usage.calls == 1
        assert tracker.usage.input_tokens == 100
        assert tracker.usage.output_tokens == 50

    @pytest.mark.asyncio
    async def test_multiple_calls_accumulate(self):
        mock = MockProvider(input_tokens=100, output_tokens=50)
        tracker = TrackingLLMProvider(mock)

        await tracker.generate([Message(role="user", content="q1")])
        await tracker.generate([Message(role="user", content="q2")])
        await tracker.generate([Message(role="user", content="q3")])

        assert tracker.usage.calls == 3
        assert tracker.usage.input_tokens == 300
        assert tracker.usage.output_tokens == 150

    @pytest.mark.asyncio
    async def test_generate_json_tracks_usage(self):
        mock = MockProvider(input_tokens=200, output_tokens=80)

        # Override stream to return valid JSON
        original_stream = mock.stream

        async def json_stream(messages, **kwargs):
            yield StreamChunk(text='{"key": "value"}')
            yield StreamChunk(
                text="",
                usage=TokenUsage(input_tokens=200, output_tokens=80),
            )

        mock.stream = json_stream
        tracker = TrackingLLMProvider(mock)

        result, usage = await tracker.generate_json([Message(role="user", content="json")])

        assert result == {"key": "value"}
        assert tracker.usage.calls == 1
        assert tracker.usage.input_tokens == 200
        assert tracker.usage.output_tokens == 80

    @pytest.mark.asyncio
    async def test_stream_tracks_usage(self):
        mock = MockProvider(input_tokens=150, output_tokens=60)
        tracker = TrackingLLMProvider(mock)

        chunks = []
        async for chunk in tracker.stream([Message(role="user", content="stream")]):
            chunks.append(chunk.text)

        assert "".join(chunks) == "Hello world"
        assert tracker.usage.calls == 1
        assert tracker.usage.input_tokens == 150
        assert tracker.usage.output_tokens == 60

    @pytest.mark.asyncio
    async def test_callbacks_emitted(self):
        mock = MockProvider(input_tokens=100, output_tokens=50)
        callbacks = MagicMock()
        tracker = TrackingLLMProvider(mock, callbacks)

        await tracker.generate([Message(role="user", content="hi")])

        callbacks.emit.assert_called_once_with(
            "llm/complete",
            input_tokens=100,
            output_tokens=50,
            total_calls=1,
            total_input_tokens=100,
            total_output_tokens=50,
        )

    @pytest.mark.asyncio
    async def test_callbacks_accumulate_totals(self):
        mock = MockProvider(input_tokens=100, output_tokens=50)
        callbacks = MagicMock()
        tracker = TrackingLLMProvider(mock, callbacks)

        await tracker.generate([Message(role="user", content="q1")])
        await tracker.generate([Message(role="user", content="q2")])

        # Second call should show accumulated totals
        last_call = callbacks.emit.call_args_list[-1]
        assert last_call.kwargs["total_calls"] == 2
        assert last_call.kwargs["total_input_tokens"] == 200
        assert last_call.kwargs["total_output_tokens"] == 100

    @pytest.mark.asyncio
    async def test_no_callbacks_is_fine(self):
        mock = MockProvider(input_tokens=100, output_tokens=50)
        tracker = TrackingLLMProvider(mock)  # No callbacks

        text, usage = await tracker.generate([Message(role="user", content="hi")])
        assert text == "Hello world"
        assert tracker.usage.calls == 1

    def test_model_property_delegation(self):
        mock = MockProvider()
        mock.model = "test-model"
        tracker = TrackingLLMProvider(mock)
        assert tracker.model == "test-model"

    def test_breakdown_records(self):
        """Verify that LLMUsage.breakdown contains per-call details."""
        mock = MockProvider(input_tokens=100, output_tokens=50)
        tracker = TrackingLLMProvider(mock)

        asyncio.get_event_loop().run_until_complete(
            tracker.generate([Message(role="user", content="hi")])
        )

        assert len(tracker.usage.breakdown) == 1
        entry = tracker.usage.breakdown[0]
        assert entry["label"] == "generate"
        assert entry["model"] == "mock-model"
        assert entry["input_tokens"] == 100
        assert entry["output_tokens"] == 50


class TestFmtTokens:
    def test_small_numbers(self):
        from mcpdb.cli.progress import fmt_tokens

        assert fmt_tokens(0) == "0"
        assert fmt_tokens(999) == "999"

    def test_thousands(self):
        from mcpdb.cli.progress import fmt_tokens

        assert fmt_tokens(1000) == "1.0k"
        assert fmt_tokens(1234) == "1.2k"
        assert fmt_tokens(12345) == "12.3k"

    def test_millions(self):
        from mcpdb.cli.progress import fmt_tokens

        assert fmt_tokens(1_000_000) == "1.0M"
        assert fmt_tokens(1_234_567) == "1.2M"
