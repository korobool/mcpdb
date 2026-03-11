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

    def set_response(self, response: dict[str, Any] | str) -> None:
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
        resp = self._default_response
        text = resp if isinstance(resp, str) else json.dumps(resp)
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
    async def test_classify_off_topic_fast_path(self):
        """Greetings and chat should be classified as off_topic without LLM."""
        llm = MockLLM()
        cb = CallbackManager()
        for question in ["hello", "Hi!", "who are you?", "thanks", "bye"]:
            state: AgentState = {
                "question": question,
                "source_context": "...",
                "active_source_ids": ["db_1"],
            }
            result = await classify(state, llm, cb)
            assert result["query_mode"] == "off_topic", f"Expected off_topic for: {question}"

    @pytest.mark.asyncio
    async def test_classify_off_topic_llm(self):
        """LLM can classify non-data questions as off_topic."""
        llm = MockLLM()
        llm.set_response({
            "mode": "off_topic",
            "reasoning": "Not a data question",
            "target_sources": [],
            "key_entities": [],
        })
        cb = CallbackManager()
        state: AgentState = {
            "question": "What is the meaning of life?",
            "source_context": "...",
            "active_source_ids": ["db_1"],
        }
        result = await classify(state, llm, cb)
        assert result["query_mode"] == "off_topic"

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


class TestClassifyQuestionStandalone:
    """Tests for the reusable classify_question() function."""

    @pytest.mark.asyncio
    async def test_allowed_modes_restricts_output(self):
        """LLM returning a metamode is remapped to default when restricted to base modes."""
        from mcpdb.agent.nodes.classify import classify_question
        from mcpdb.agent.state import BASE_MODES

        llm = MockLLM()
        llm.set_response({
            "mode": "deep",
            "reasoning": "Multi-investigation",
            "target_sources": [],
            "key_entities": [],
        })

        result = await classify_question(
            question="Investigate everything",
            source_context="test schema",
            llm=llm,
            allowed_modes=BASE_MODES,
        )
        # "deep" not in BASE_MODES → falls back to "simple"
        assert result["mode"] == "simple"

    @pytest.mark.asyncio
    async def test_allowed_modes_accepts_valid(self):
        """LLM returning a valid base mode is accepted when restricted."""
        from mcpdb.agent.nodes.classify import classify_question
        from mcpdb.agent.state import BASE_MODES

        llm = MockLLM()
        llm.set_response({
            "mode": "extended",
            "reasoning": "Complex analysis",
            "target_sources": ["db"],
            "key_entities": ["orders"],
        })

        result = await classify_question(
            question="Do comprehensive EDA",
            source_context="test schema",
            llm=llm,
            allowed_modes=BASE_MODES,
        )
        assert result["mode"] == "extended"

    @pytest.mark.asyncio
    async def test_fast_path_quick_respected_in_allowed(self):
        """Fast-path 'quick' detection works when quick is in allowed_modes."""
        from mcpdb.agent.nodes.classify import classify_question
        from mcpdb.agent.state import BASE_MODES

        llm = MockLLM()
        # Should not be called — fast path matches
        llm.set_response({"mode": "simple"})

        result = await classify_question(
            question="What tables exist?",
            source_context="test schema",
            llm=llm,
            allowed_modes=BASE_MODES,
        )
        assert result["mode"] == "quick"
        assert result["reasoning"] == "fast-path pattern match"

    @pytest.mark.asyncio
    async def test_fast_path_quick_skipped_when_not_allowed(self):
        """Fast-path 'quick' is skipped when quick is not in allowed_modes."""
        from mcpdb.agent.nodes.classify import classify_question

        allowed = frozenset({"simple", "extended"})
        llm = MockLLM()
        llm.set_response({
            "mode": "simple",
            "reasoning": "LLM decided",
            "target_sources": [],
            "key_entities": [],
        })

        result = await classify_question(
            question="What tables exist?",
            source_context="test schema",
            llm=llm,
            allowed_modes=allowed,
        )
        # Fast-path would return "quick" but it's not allowed → falls through to LLM
        assert result["mode"] == "simple"

    @pytest.mark.asyncio
    async def test_fast_path_off_topic_skipped_when_not_allowed(self):
        """Fast-path 'off_topic' is skipped when off_topic not in allowed_modes."""
        from mcpdb.agent.nodes.classify import classify_question
        from mcpdb.agent.state import BASE_MODES

        llm = MockLLM()
        llm.set_response({
            "mode": "simple",
            "reasoning": "Fallback",
            "target_sources": [],
            "key_entities": [],
        })

        result = await classify_question(
            question="hello",
            source_context="test schema",
            llm=llm,
            allowed_modes=BASE_MODES,  # off_topic not in BASE_MODES
        )
        # Fast-path would return "off_topic" but it's not allowed → LLM
        assert result["mode"] == "simple"

    @pytest.mark.asyncio
    async def test_all_modes_default(self):
        """Without allowed_modes, all modes including metamodes are available."""
        from mcpdb.agent.nodes.classify import classify_question

        llm = MockLLM()
        llm.set_response({
            "mode": "deep",
            "reasoning": "Research needed",
            "target_sources": [],
            "key_entities": [],
        })

        result = await classify_question(
            question="Investigate patterns",
            source_context="test schema",
            llm=llm,
        )
        assert result["mode"] == "deep"


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
        llm.set_response("ESCALATE")
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
        """Simple mode runs the pipeline, synthesizes even with empty LLM plan."""
        llm = MockLLM()
        # Plan call returns empty steps — but agent should still produce a response
        # via fallback plan or context synthesis
        llm.set_response({
            "analysis": "test",
            "approach": "test",
            "steps": [],
        })
        registry = SourceRegistry()
        registry.add_source(MockQueryableSource())

        state = await run_agent(
            question="Show top customers",
            registry=registry,
            llm=llm,
            mode_override="simple",
        )

        # Agent should still produce a response (not dead-end)
        assert state["response"] is not None
        assert len(state["response"]) > 0
        registry.close_all()


# ---------------------------------------------------------------------------
# Mode taxonomy tests
# ---------------------------------------------------------------------------


class TestModeTaxonomy:
    """Tests for BASE_MODES, META_MODES, ALL_MODES and helpers."""

    def test_base_modes_content(self):
        from mcpdb.agent.state import BASE_MODES
        assert BASE_MODES == frozenset({"quick", "simple", "extended", "optimization_required"})

    def test_meta_modes_content(self):
        from mcpdb.agent.state import META_MODES
        assert META_MODES == frozenset({"deep", "sequential"})

    def test_all_modes_is_union(self):
        from mcpdb.agent.state import BASE_MODES, META_MODES, ALL_MODES
        assert ALL_MODES == BASE_MODES | META_MODES | frozenset({"off_topic"})

    def test_no_overlap_base_meta(self):
        from mcpdb.agent.state import BASE_MODES, META_MODES
        assert BASE_MODES & META_MODES == frozenset()

    def test_is_base_mode(self):
        from mcpdb.agent.state import is_base_mode
        assert is_base_mode("quick") is True
        assert is_base_mode("simple") is True
        assert is_base_mode("extended") is True
        assert is_base_mode("optimization_required") is True
        assert is_base_mode("deep") is False
        assert is_base_mode("sequential") is False
        assert is_base_mode("off_topic") is False
        assert is_base_mode("nonsense") is False

    def test_is_meta_mode(self):
        from mcpdb.agent.state import is_meta_mode
        assert is_meta_mode("deep") is True
        assert is_meta_mode("sequential") is True
        assert is_meta_mode("simple") is False
        assert is_meta_mode("off_topic") is False


# ---------------------------------------------------------------------------
# dispatch_base_mode tests
# ---------------------------------------------------------------------------


class TestDispatchBaseMode:
    """Tests for the shared dispatch_base_mode utility."""

    @pytest.mark.asyncio
    async def test_dispatch_simple(self):
        """dispatch_base_mode routes 'simple' to run_simple."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from mcpdb.agent.subgraphs import dispatch_base_mode
        from mcpdb.agent.callbacks import CallbackManager

        state: AgentState = {
            "question": "Test",
            "query_mode": "simple",
            "source_context": "",
            "active_source_ids": [],
        }

        mock_result = {**state, "response": "simple result"}
        with patch("mcpdb.agent.subgraphs.simple.run_simple", new_callable=AsyncMock, return_value=mock_result) as mock_simple:
            result = await dispatch_base_mode(state, MagicMock(), CallbackManager(), MagicMock())
            mock_simple.assert_awaited_once()
            assert result["response"] == "simple result"

    @pytest.mark.asyncio
    async def test_dispatch_extended(self):
        """dispatch_base_mode routes 'extended' to run_extended."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from mcpdb.agent.subgraphs import dispatch_base_mode
        from mcpdb.agent.callbacks import CallbackManager

        state: AgentState = {
            "question": "Test",
            "query_mode": "extended",
            "source_context": "",
            "active_source_ids": [],
        }

        mock_result = {**state, "response": "extended result"}
        with patch("mcpdb.agent.subgraphs.extended.run_extended", new_callable=AsyncMock, return_value=mock_result) as mock_ext:
            result = await dispatch_base_mode(state, MagicMock(), CallbackManager(), MagicMock())
            mock_ext.assert_awaited_once()
            assert result["response"] == "extended result"

    @pytest.mark.asyncio
    async def test_dispatch_optimization(self):
        """dispatch_base_mode routes 'optimization_required' to run_optimization."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from mcpdb.agent.subgraphs import dispatch_base_mode
        from mcpdb.agent.callbacks import CallbackManager

        state: AgentState = {
            "question": "Test",
            "query_mode": "optimization_required",
            "source_context": "",
            "active_source_ids": [],
        }

        mock_result = {**state, "response": "opt result"}
        with patch("mcpdb.agent.subgraphs.optimization.run_optimization", new_callable=AsyncMock, return_value=mock_result) as mock_opt:
            result = await dispatch_base_mode(state, MagicMock(), CallbackManager(), MagicMock())
            mock_opt.assert_awaited_once()
            assert result["response"] == "opt result"

    @pytest.mark.asyncio
    async def test_dispatch_quick_no_escalation(self):
        """dispatch_base_mode routes 'quick' to run_quick; no escalation if complete."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from mcpdb.agent.subgraphs import dispatch_base_mode
        from mcpdb.agent.callbacks import CallbackManager

        state: AgentState = {
            "question": "What tables?",
            "query_mode": "quick",
            "source_context": "test",
        }

        mock_result = {**state, "response": "quick result", "validation_result": "complete"}
        with patch("mcpdb.agent.subgraphs.quick.run_quick", new_callable=AsyncMock, return_value=mock_result) as mock_quick:
            result = await dispatch_base_mode(state, MagicMock(), CallbackManager(), MagicMock())
            mock_quick.assert_awaited_once()
            assert result["response"] == "quick result"

    @pytest.mark.asyncio
    async def test_dispatch_quick_escalates_to_simple(self):
        """dispatch_base_mode escalates quick → simple when needs_data."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from mcpdb.agent.subgraphs import dispatch_base_mode
        from mcpdb.agent.callbacks import CallbackManager

        state: AgentState = {
            "question": "Show top customers",
            "query_mode": "quick",
            "source_context": "test",
        }

        quick_result = {**state, "response": None, "validation_result": "needs_data", "query_mode": "simple"}
        simple_result = {**quick_result, "response": "data result"}
        with patch("mcpdb.agent.subgraphs.quick.run_quick", new_callable=AsyncMock, return_value=quick_result) as mock_quick, \
             patch("mcpdb.agent.subgraphs.simple.run_simple", new_callable=AsyncMock, return_value=simple_result) as mock_simple:
            result = await dispatch_base_mode(state, MagicMock(), CallbackManager(), MagicMock())
            mock_quick.assert_awaited_once()
            mock_simple.assert_awaited_once()
            assert result["response"] == "data result"

    @pytest.mark.asyncio
    async def test_dispatch_unknown_mode_defaults_to_simple(self):
        """Unknown mode falls back to simple."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from mcpdb.agent.subgraphs import dispatch_base_mode
        from mcpdb.agent.callbacks import CallbackManager

        state: AgentState = {
            "question": "Test",
            "query_mode": "unknown_mode",
            "source_context": "",
        }

        mock_result = {**state, "response": "fallback", "query_mode": "simple"}
        with patch("mcpdb.agent.subgraphs.simple.run_simple", new_callable=AsyncMock, return_value=mock_result) as mock_simple:
            result = await dispatch_base_mode(state, MagicMock(), CallbackManager(), MagicMock())
            mock_simple.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_missing_mode_defaults_to_simple(self):
        """Missing query_mode defaults to simple."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from mcpdb.agent.subgraphs import dispatch_base_mode
        from mcpdb.agent.callbacks import CallbackManager

        state: AgentState = {
            "question": "Test",
            "source_context": "",
        }

        mock_result = {**state, "response": "default simple"}
        with patch("mcpdb.agent.subgraphs.simple.run_simple", new_callable=AsyncMock, return_value=mock_result) as mock_simple:
            result = await dispatch_base_mode(state, MagicMock(), CallbackManager(), MagicMock())
            mock_simple.assert_awaited_once()
