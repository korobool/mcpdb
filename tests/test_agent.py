"""Tests for v0.3.0-v0.3.3 — Agent Foundation.

Tests agent state, callbacks, classify node, quick mode, and ask_question.
Uses a mock LLM provider to avoid real API calls.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import pytest

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager, StreamingEvent
from mcpdb.agent.nodes.classify import classify
from mcpdb.agent.subgraphs.quick import run_quick
from mcpdb.agent.graph import run_agent
from mcpdb.llm.provider import LLMProvider, Message, StreamChunk
from mcpdb.llm.config import TokenUsage
from mcpdb.sources.registry import SourceRegistry
from mcpdb.sources.base import (
    ColumnInfo, DataSource, QueryableSource, SourceMetadata, SourceType, TableInfo,
)


# --- Mock LLM provider ---


class MockLLM(LLMProvider):
    """LLM that returns configurable JSON responses."""

    def __init__(self, responses: dict[str, Any] | None = None):
        self._responses = responses or {}
        self._default_response = {"mode": "simple", "reasoning": "default"}
        self.calls: list[str] = []

    def set_response(self, response: dict[str, Any]) -> None:
        self._default_response = response

    async def stream(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        self.calls.append(messages[-1].content[:50])
        text = json.dumps(self._default_response)
        yield StreamChunk(text=text)
        yield StreamChunk(text="", usage=TokenUsage(input_tokens=100, output_tokens=50))


# --- Mock source ---


class MockQueryableSource(QueryableSource):
    def __init__(self, source_id: str = "db_test"):
        self._id = source_id

    @property
    def source_type(self) -> SourceType:
        return SourceType.DATABASE

    def get_metadata(self) -> SourceMetadata:
        return SourceMetadata(
            source_id=self._id,
            source_type=SourceType.DATABASE,
            display_name="Test DB",
            tables=[
                TableInfo(name="users", columns=[
                    ColumnInfo(name="id", dtype="INTEGER"),
                    ColumnInfo(name="name", dtype="TEXT"),
                ], row_count=100),
                TableInfo(name="orders", columns=[
                    ColumnInfo(name="id", dtype="INTEGER"),
                    ColumnInfo(name="amount", dtype="REAL"),
                ], row_count=5000),
            ],
            capabilities={"sql"},
        )

    def get_context_description(self) -> str:
        return "Database: Test DB\n  - users (100 rows)\n  - orders (5000 rows)"

    def execute_query(self, query, max_rows=100):
        raise NotImplementedError

    def get_sample(self, table_name, limit=5):
        raise NotImplementedError

    def close(self):
        pass


# --- Tests ---


class TestAgentState:
    def test_create_minimal(self):
        state: AgentState = {
            "question": "What tables exist?",
            "source_context": "Test DB",
            "active_source_ids": ["db_1"],
        }
        assert state["question"] == "What tables exist?"

    def test_create_full(self):
        state: AgentState = {
            "question": "Show top 10 customers",
            "source_context": "...",
            "active_source_ids": ["db_1"],
            "query_mode": "simple",
            "target_sources": ["db_1"],
            "requires_cross_source": False,
            "key_entities": ["customers"],
            "response": None,
            "validation_result": None,
            "replan_count": 0,
            "artifacts": [],
            "execution_log": [],
            "max_retries": 3,
        }
        assert state["query_mode"] == "simple"


class TestCallbackManager:
    def test_emit_and_receive(self):
        cb = CallbackManager()
        received = []
        cb.add_listener(lambda e: received.append(e))

        cb.emit("test/event", key="value")

        assert len(received) == 1
        assert received[0].type == "test/event"
        assert received[0].data["key"] == "value"

    def test_multiple_listeners(self):
        cb = CallbackManager()
        counts = [0, 0]
        cb.add_listener(lambda e: counts.__setitem__(0, counts[0] + 1))
        cb.add_listener(lambda e: counts.__setitem__(1, counts[1] + 1))

        cb.emit("test")
        assert counts == [1, 1]

    def test_get_events(self):
        cb = CallbackManager()
        cb.emit("a")
        cb.emit("b")
        events = cb.get_events()
        assert len(events) == 2
        assert events[0].type == "a"
        assert events[1].type == "b"

    def test_clear(self):
        cb = CallbackManager()
        cb.emit("a")
        cb.clear()
        assert len(cb.get_events()) == 0

    def test_remove_listener(self):
        cb = CallbackManager()
        received = []
        listener = lambda e: received.append(e)
        cb.add_listener(listener)
        cb.emit("before")
        cb.remove_listener(listener)
        cb.emit("after")
        assert len(received) == 1

    def test_listener_error_doesnt_crash(self):
        cb = CallbackManager()
        cb.add_listener(lambda e: 1 / 0)  # Raises ZeroDivisionError
        cb.emit("test")  # Should not raise


class TestClassifyNode:
    @pytest.mark.asyncio
    async def test_classify_quick(self):
        llm = MockLLM()
        llm.set_response({
            "mode": "quick",
            "reasoning": "Schema question",
            "target_sources": ["db_1"],
            "requires_cross_source": False,
            "key_entities": ["tables"],
        })
        cb = CallbackManager()
        state: AgentState = {
            "question": "What tables exist?",
            "source_context": "Database with users and orders tables",
            "active_source_ids": ["db_1"],
        }

        result = await classify(state, llm, cb)
        assert result["query_mode"] == "quick"
        assert result["target_sources"] == ["db_1"]

        events = cb.get_events()
        types = [e.type for e in events]
        assert "classify/start" in types
        assert "classify/complete" in types

    @pytest.mark.asyncio
    async def test_classify_simple(self):
        llm = MockLLM()
        llm.set_response({
            "mode": "simple",
            "reasoning": "Data query",
            "target_sources": ["db_1"],
            "key_entities": ["customers"],
        })
        cb = CallbackManager()
        state: AgentState = {
            "question": "Show top 10 customers",
            "source_context": "...",
            "active_source_ids": ["db_1"],
        }

        result = await classify(state, llm, cb)
        assert result["query_mode"] == "simple"

    @pytest.mark.asyncio
    async def test_classify_invalid_mode_defaults_simple(self):
        llm = MockLLM()
        llm.set_response({"mode": "invalid_mode"})
        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "source_context": "...",
            "active_source_ids": [],
        }

        result = await classify(state, llm, cb)
        assert result["query_mode"] == "simple"


class TestQuickMode:
    @pytest.mark.asyncio
    async def test_quick_answers_from_context(self):
        llm = MockLLM()
        llm.set_response({
            "action": "answer",
            "text": "There are 2 tables: users (100 rows) and orders (5000 rows).",
        })
        cb = CallbackManager()
        state: AgentState = {
            "question": "What tables exist?",
            "source_context": "users (100 rows), orders (5000 rows)",
        }

        result = await run_quick(state, llm, cb)
        assert result["validation_result"] == "complete"
        assert "2 tables" in result["response"]

    @pytest.mark.asyncio
    async def test_quick_escalates(self):
        llm = MockLLM()
        llm.set_response({
            "action": "escalate",
            "reason": "needs actual row data",
        })
        cb = CallbackManager()
        state: AgentState = {
            "question": "Show me the top customers",
            "source_context": "...",
        }

        result = await run_quick(state, llm, cb)
        assert result["validation_result"] == "needs_data"
        assert result["query_mode"] == "simple"

        types = [e.type for e in cb.get_events()]
        assert "quick/escalate" in types


class TestOrchestratorGraph:
    @pytest.mark.asyncio
    async def test_full_quick_flow(self):
        llm = MockLLM()
        # First call: classify → quick
        # Second call: quick answer
        call_count = [0]
        original_stream = llm.stream

        async def multi_stream(messages, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # Classify call
                llm.set_response({
                    "mode": "quick",
                    "reasoning": "Schema question",
                    "target_sources": ["db_test"],
                    "key_entities": [],
                })
            else:
                # Quick answer call
                llm.set_response({
                    "action": "answer",
                    "text": "There are 2 tables.",
                })
            async for chunk in original_stream(messages, **kwargs):
                yield chunk

        llm.stream = multi_stream

        registry = SourceRegistry()
        registry.add_source(MockQueryableSource())

        cb = CallbackManager()
        state = await run_agent(
            question="What tables exist?",
            registry=registry,
            llm=llm,
            callbacks=cb,
        )

        assert state.get("response") is not None
        types = [e.type for e in cb.get_events()]
        assert "classify/start" in types
        assert "agent/complete" in types

        registry.close_all()

    @pytest.mark.asyncio
    async def test_mode_override(self):
        llm = MockLLM()
        llm.set_response({"action": "answer", "text": "Quick answer."})

        registry = SourceRegistry()
        registry.add_source(MockQueryableSource())

        cb = CallbackManager()
        state = await run_agent(
            question="What tables?",
            registry=registry,
            llm=llm,
            callbacks=cb,
            mode_override="quick",
        )

        types = [e.type for e in cb.get_events()]
        assert "classify/override" in types
        assert "classify/start" not in types  # Skipped classification

        registry.close_all()

    @pytest.mark.asyncio
    async def test_simple_mode_runs(self):
        """Simple mode now runs the real pipeline (tested in detail in test_simple_mode.py)."""
        llm = MockLLM()
        # Plan call
        llm.set_response({
            "analysis": "test",
            "approach": "test",
            "steps": [],  # Empty plan → early exit with message
        })
        registry = SourceRegistry()
        registry.add_source(MockQueryableSource())

        state = await run_agent(
            question="Show top customers",
            registry=registry,
            llm=llm,
            mode_override="simple",
        )

        # With empty plan, simple mode returns "could not create" message
        assert state["response"] is not None
        assert "could not create" in state["response"].lower()
        registry.close_all()
