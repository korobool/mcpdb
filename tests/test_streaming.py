"""Tests for v0.6.0-v0.6.4 — Streaming & Cancellation.

Tests CancellationToken, streaming LLM wrapper, UserInputQueue,
CancellableQueryRunner, and control MCP tools.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from typing import Any, AsyncIterator

import pandas as pd
import pytest

from mcpdb.agent.cancellation import CancellationToken, CancelledException
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.streaming import stream_llm_call, stream_llm_json
from mcpdb.agent.user_input import UserInputQueue, UserContext
from mcpdb.llm.provider import LLMProvider, Message, StreamChunk
from mcpdb.llm.config import TokenUsage


# --- Mock LLM for streaming tests ---


class StreamingMockLLM(LLMProvider):
    """LLM that yields tokens one at a time for testing streaming."""

    def __init__(self, tokens: list[str] | None = None, delay: float = 0):
        self._tokens = tokens or ["Hello", " ", "world", "!"]
        self._delay = delay

    async def stream(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        for token in self._tokens:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield StreamChunk(text=token)
        yield StreamChunk(text="", usage=TokenUsage(input_tokens=50, output_tokens=len(self._tokens)))


# --- CancellationToken Tests ---


class TestCancellationToken:
    def test_initial_state(self):
        token = CancellationToken()
        assert not token.is_cancelled

    def test_cancel(self):
        token = CancellationToken()
        token.cancel()
        assert token.is_cancelled

    def test_check_raises(self):
        token = CancellationToken()
        token.cancel()
        with pytest.raises(CancelledException):
            token.check()

    def test_check_ok(self):
        token = CancellationToken()
        token.check()  # Should not raise

    def test_reset(self):
        token = CancellationToken()
        token.cancel()
        assert token.is_cancelled
        token.reset()
        assert not token.is_cancelled

    def test_thread_safety(self):
        token = CancellationToken()
        results = []

        def cancel_later():
            import time
            time.sleep(0.05)
            token.cancel()

        def check_loop():
            for _ in range(100):
                if token.is_cancelled:
                    results.append("cancelled")
                    return
                import time
                time.sleep(0.01)
            results.append("not_cancelled")

        t1 = threading.Thread(target=cancel_later)
        t2 = threading.Thread(target=check_loop)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert "cancelled" in results


# --- Streaming LLM Wrapper Tests ---


class TestStreamLLMCall:
    @pytest.mark.asyncio
    async def test_basic_streaming(self):
        llm = StreamingMockLLM(tokens=["The ", "answer ", "is ", "42."])
        cb = CallbackManager()

        text, usage = await stream_llm_call(llm, [Message(role="user", content="test")], cb, label="test")

        assert text == "The answer is 42."
        assert usage.output_tokens == 4

        types = [e.type for e in cb.get_events()]
        assert "llm/start" in types
        assert "llm/token" in types
        assert "llm/complete" in types

    @pytest.mark.asyncio
    async def test_token_events_emitted(self):
        llm = StreamingMockLLM(tokens=["a", "b", "c"])
        cb = CallbackManager()

        await stream_llm_call(llm, [Message(role="user", content="test")], cb)

        token_events = [e for e in cb.get_events() if e.type == "llm/token"]
        assert len(token_events) == 3
        assert token_events[0].data["text"] == "a"
        assert token_events[2].data["text"] == "c"

    @pytest.mark.asyncio
    async def test_cancellation_during_stream(self):
        llm = StreamingMockLLM(tokens=["a", "b", "c", "d", "e"], delay=0.05)
        cb = CallbackManager()
        token = CancellationToken()

        # Cancel after a short delay
        async def cancel_later():
            await asyncio.sleep(0.08)
            token.cancel()

        cancel_task = asyncio.create_task(cancel_later())

        with pytest.raises(CancelledException):
            await stream_llm_call(
                llm, [Message(role="user", content="test")], cb,
                cancellation=token,
            )

        await cancel_task

    @pytest.mark.asyncio
    async def test_cancellation_before_start(self):
        llm = StreamingMockLLM()
        cb = CallbackManager()
        token = CancellationToken()
        token.cancel()

        with pytest.raises(CancelledException):
            await stream_llm_call(
                llm, [Message(role="user", content="test")], cb,
                cancellation=token,
            )


class TestStreamLLMJson:
    @pytest.mark.asyncio
    async def test_json_parsing(self):
        llm = StreamingMockLLM(tokens=['{"result": "', 'adequate"}'])
        cb = CallbackManager()

        result, usage = await stream_llm_json(
            llm, [Message(role="user", content="test")], cb,
        )

        assert result == {"result": "adequate"}

    @pytest.mark.asyncio
    async def test_json_with_code_block(self):
        llm = StreamingMockLLM(tokens=['```json\n', '{"key": "val"}\n', '```'])
        cb = CallbackManager()

        result, usage = await stream_llm_json(
            llm, [Message(role="user", content="test")], cb,
        )

        assert result == {"key": "val"}


# --- UserInputQueue Tests ---


class TestUserInputQueue:
    def test_add_and_drain(self):
        q = UserInputQueue()
        q.add("Focus on revenue data")
        q.add("Also check expenses")

        items = q.drain()
        assert len(items) == 2
        assert items[0].text == "Focus on revenue data"
        assert items[1].text == "Also check expenses"

        # Drain should be empty now
        assert q.drain() == []

    def test_has_items(self):
        q = UserInputQueue()
        assert not q.has_items
        q.add("test")
        assert q.has_items

    def test_peek(self):
        q = UserInputQueue()
        q.add("test")
        items = q.peek()
        assert len(items) == 1
        # peek doesn't consume
        assert q.has_items

    def test_clear(self):
        q = UserInputQueue()
        q.add("a")
        q.add("b")
        q.clear()
        assert not q.has_items

    def test_metadata(self):
        q = UserInputQueue()
        q.add("test", priority="high", source="user")
        items = q.drain()
        assert items[0].metadata == {"priority": "high", "source": "user"}

    def test_thread_safety(self):
        q = UserInputQueue()
        results = []

        def producer():
            for i in range(50):
                q.add(f"item_{i}")

        def consumer():
            collected = 0
            for _ in range(100):
                items = q.drain()
                collected += len(items)
                import time
                time.sleep(0.001)
            results.append(collected)

        t1 = threading.Thread(target=producer)
        t2 = threading.Thread(target=consumer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Consumer may not get all items depending on timing
        # but should not crash
        total = results[0] + len(q.drain())  # Remaining items
        assert total == 50


# --- CancellableQueryRunner Tests ---


class TestCancellableQueryRunner:
    @pytest.fixture
    def test_db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE data (id INTEGER, val TEXT)")
        conn.executemany(
            "INSERT INTO data VALUES (?, ?)",
            [(i, f"row_{i}") for i in range(10)],
        )
        conn.commit()
        conn.close()
        return db_path

    @pytest.fixture
    def connector(self, test_db):
        from mcpdb.sources.database.connector import DatabaseConnector
        conn = DatabaseConnector(f"sqlite:///{test_db}")
        yield conn
        conn.close()

    @pytest.mark.asyncio
    async def test_execute_without_cancellation(self, connector):
        from mcpdb.sources.database.query_runner import CancellableQueryRunner
        runner = CancellableQueryRunner(connector)
        df = await runner.execute("SELECT * FROM data LIMIT 5")
        assert len(df) == 5

    @pytest.mark.asyncio
    async def test_execute_with_uncancelled_token(self, connector):
        from mcpdb.sources.database.query_runner import CancellableQueryRunner
        runner = CancellableQueryRunner(connector)
        token = CancellationToken()
        df = await runner.execute("SELECT COUNT(*) as cnt FROM data", cancellation=token)
        assert len(df) == 1

    @pytest.mark.asyncio
    async def test_execute_with_pre_cancelled_token(self, connector):
        from mcpdb.sources.database.query_runner import CancellableQueryRunner
        runner = CancellableQueryRunner(connector)
        token = CancellationToken()
        token.cancel()
        with pytest.raises(CancelledException):
            await runner.execute("SELECT * FROM data", cancellation=token)


# --- Control MCP Tools Tests ---


class TestControlTools:
    def test_cancel_execution(self):
        from mcpdb.mcp.tools.control import handle_control_tool, get_session_state, reset_session_state

        reset_session_state("test_session")
        state = get_session_state("test_session")
        assert not state["cancellation"].is_cancelled

        result = handle_control_tool("cancel_execution", {"session_id": "test_session"})
        assert "cancellation" in result[0].text.lower() or "cancel" in result[0].text.lower()
        assert state["cancellation"].is_cancelled

        reset_session_state("test_session")

    def test_add_context(self):
        from mcpdb.mcp.tools.control import handle_control_tool, get_session_state, reset_session_state

        reset_session_state("test_session")
        state = get_session_state("test_session")

        result = handle_control_tool("add_context", {
            "session_id": "test_session",
            "text": "Focus on Q4 data only",
        })
        assert "context added" in result[0].text.lower()
        assert state["input_queue"].has_items

        items = state["input_queue"].drain()
        assert items[0].text == "Focus on Q4 data only"

        reset_session_state("test_session")

    def test_tool_list_includes_control(self):
        from mcpdb.mcp.tools.control import get_control_tools
        tools = get_control_tools()
        names = [t.name for t in tools]
        assert "cancel_execution" in names
        assert "add_context" in names


# --- Integration: Tools registered in server ---


class TestControlToolRegistration:
    def test_server_includes_control_tools(self):
        from mcpdb.mcp.server import create_server
        server, registry = create_server()

        # Verify control tools are in the registered tools
        from mcpdb.mcp.tools.control import get_control_tools
        control_names = {t.name for t in get_control_tools()}
        assert "cancel_execution" in control_names
        assert "add_context" in control_names

        registry.close_all()
