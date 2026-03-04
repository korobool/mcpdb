"""Tests for v1.1.0-v1.1.5 — Cost Awareness & EXPLAIN.

Tests fast scan, heuristic check, EXPLAIN integration, strategy gate,
submit_strategy MCP tool, and LLM cost tracking.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, AsyncIterator

import pandas as pd
import pytest

from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.state import AgentState
from mcpdb.agent.nodes.cost_check import (
    fast_scan,
    heuristic_check,
    run_explain,
    cost_check,
    CostAnalysis,
)
from mcpdb.agent.nodes.strategy_gate import (
    strategy_gate,
    save_pending_strategy,
    get_pending_strategy,
    consume_pending_strategy,
    clear_pending_strategies,
)
from mcpdb.llm.provider import LLMProvider, Message, StreamChunk
from mcpdb.llm.config import TokenUsage
from mcpdb.sources.registry import SourceRegistry
from mcpdb.sources.base import (
    ColumnInfo, QueryableSource, SourceMetadata, SourceType, TableInfo,
)


# --- MockLLM ---


class MockLLM(LLMProvider):
    def __init__(self):
        self._responses: list[dict | str] = []
        self._call_index = 0

    def queue(self, *responses):
        self._responses.extend(responses)

    async def stream(self, messages, *, system=None, max_tokens=4096, temperature=0.0, **kwargs):
        if self._call_index < len(self._responses):
            resp = self._responses[self._call_index]
        else:
            resp = {"error": "no more responses"}
        self._call_index += 1
        text = resp if isinstance(resp, str) else json.dumps(resp)
        yield StreamChunk(text=text)
        yield StreamChunk(text="", usage=TokenUsage(input_tokens=50, output_tokens=20))


# --- Mock source with configurable table sizes ---


class MockSource(QueryableSource):
    def __init__(self, tables: list[TableInfo] | None = None, source_id: str = "test"):
        self._id = source_id
        self._tables = tables or [
            TableInfo(name="orders", columns=[
                ColumnInfo(name="id", dtype="INTEGER"),
            ], row_count=5_000_000),
            TableInfo(name="users", columns=[
                ColumnInfo(name="id", dtype="INTEGER"),
            ], row_count=100),
        ]

    @property
    def source_type(self):
        return SourceType.DATABASE

    def get_metadata(self):
        return SourceMetadata(
            source_id=self._id,
            source_type=SourceType.DATABASE,
            display_name="Test",
            tables=self._tables,
            capabilities={"sql"},
        )

    def get_context_description(self):
        return "\n".join(f"  - {t.name} ({t.row_count} rows)" for t in self._tables)

    def execute_query(self, query, max_rows=100):
        raise NotImplementedError("MockSource doesn't execute")

    def get_sample(self, table_name, limit=5):
        raise NotImplementedError

    def close(self):
        pass


@pytest.fixture
def large_registry():
    reg = SourceRegistry()
    reg.add_source(MockSource())
    yield reg
    reg.close_all()


@pytest.fixture
def small_registry():
    reg = SourceRegistry()
    reg.add_source(MockSource(tables=[
        TableInfo(name="items", columns=[ColumnInfo(name="id", dtype="INTEGER")], row_count=50),
    ]))
    yield reg
    reg.close_all()


# --- Fast Scan Tests ---


class TestFastScan:
    def test_has_limit(self):
        result = fast_scan("SELECT * FROM orders LIMIT 10")
        assert result["has_limit"] is True

    def test_has_top(self):
        result = fast_scan("SELECT TOP 10 * FROM orders")
        assert result["has_limit"] is True

    def test_has_tablesample(self):
        result = fast_scan("SELECT * FROM orders TABLESAMPLE SYSTEM(5)")
        assert result["has_sampling"] is True

    def test_has_aggregate(self):
        result = fast_scan("SELECT COUNT(*) FROM orders GROUP BY status")
        assert result["has_aggregate"] is True

    def test_no_patterns(self):
        result = fast_scan("SELECT * FROM orders")
        assert result["has_limit"] is False
        assert result["has_sampling"] is False
        assert result["has_aggregate"] is False

    def test_case_insensitive(self):
        result = fast_scan("select * from orders limit 5")
        assert result["has_limit"] is True


# --- Heuristic Check Tests ---


class TestHeuristicCheck:
    def test_with_limit_is_cheap(self, large_registry):
        step = {"action": "sql", "code": "SELECT * FROM orders LIMIT 10", "source_id": "test"}
        result = heuristic_check(step, "test", large_registry)
        assert result.decision == "not_required"

    def test_no_large_tables_is_cheap(self, small_registry):
        step = {"action": "sql", "code": "SELECT * FROM items", "source_id": "test"}
        result = heuristic_check(step, "test", small_registry)
        assert result.decision == "not_required"

    def test_large_table_full_scan(self, large_registry):
        step = {"action": "sql", "code": "SELECT * FROM orders", "source_id": "test"}
        result = heuristic_check(step, "test", large_registry)
        assert result.decision == "necessary"
        assert "orders" in result.large_tables

    def test_large_table_aggregate(self, large_registry):
        step = {
            "action": "sql",
            "code": "SELECT COUNT(*) FROM orders GROUP BY status",
            "source_id": "test",
        }
        result = heuristic_check(step, "test", large_registry)
        assert result.decision == "recommended"

    def test_small_table_referenced(self, large_registry):
        step = {"action": "sql", "code": "SELECT * FROM users", "source_id": "test"}
        result = heuristic_check(step, "test", large_registry)
        assert result.decision == "not_required"


# --- EXPLAIN Integration Tests ---


class TestExplainIntegration:
    @pytest.fixture
    def sqlite_registry(self, tmp_path):
        """Real SQLite source for EXPLAIN tests."""
        from mcpdb.sources.database.source import DatabaseSource
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE test_data (id INTEGER PRIMARY KEY, val TEXT)")
        conn.executemany(
            "INSERT INTO test_data VALUES (?, ?)",
            [(i, f"val_{i}") for i in range(10)],
        )
        conn.commit()
        conn.close()

        source = DatabaseSource(f"sqlite:///{db_path}")
        reg = SourceRegistry()
        reg.add_source(source)
        yield reg
        reg.close_all()

    def test_explain_returns_result(self, sqlite_registry):
        source_id = sqlite_registry.list_sources()[0].source_id
        source = sqlite_registry.get_source(source_id)
        # Verify the source has a dialect
        assert hasattr(source, "dialect")
        assert source.dialect is not None
        result = run_explain("SELECT * FROM test_data", source_id, sqlite_registry)
        assert result is not None, f"EXPLAIN returned None for source_id={source_id}"
        assert "raw" in result

    def test_explain_bad_query(self, sqlite_registry):
        source_id = sqlite_registry.list_sources()[0].source_id
        result = run_explain("SELECT * FROM nonexistent", source_id, sqlite_registry)
        assert result is None  # EXPLAIN failed gracefully


# --- Cost Check Node Tests ---


class TestCostCheckNode:
    @pytest.mark.asyncio
    async def test_cheap_query_passes(self, small_registry):
        llm = MockLLM()
        cb = CallbackManager()
        state: AgentState = {
            "question": "Count items",
            "plan": {
                "steps": [{
                    "action": "sql",
                    "source_id": "test",
                    "code": "SELECT COUNT(*) FROM items LIMIT 1",
                }],
            },
        }

        result = await cost_check(state, llm, cb, small_registry)
        assert result["cost_analysis"]["decision"] == "not_required"

        types = [e.type for e in cb.get_events()]
        assert "cost_check/start" in types
        assert "cost_check/complete" in types

    @pytest.mark.asyncio
    async def test_expensive_query_flagged(self, large_registry):
        llm = MockLLM()
        llm.queue({"decision": "necessary", "reason": "Full scan on 5M row table", "estimated_rows": 5000000})

        cb = CallbackManager()
        state: AgentState = {
            "question": "All orders",
            "plan": {
                "steps": [{
                    "action": "sql",
                    "source_id": "test",
                    "code": "SELECT * FROM orders",
                }],
            },
        }

        result = await cost_check(state, llm, cb, large_registry)
        assert result["cost_analysis"]["decision"] in ("recommended", "necessary")

    @pytest.mark.asyncio
    async def test_non_sql_steps_skipped(self, small_registry):
        llm = MockLLM()
        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "plan": {
                "steps": [
                    {"action": "python", "code": "print('hello')"},
                    {"action": "schema", "source_id": "test"},
                ],
            },
        }

        result = await cost_check(state, llm, cb, small_registry)
        assert result["cost_analysis"]["decision"] == "not_required"


# --- Strategy Gate Tests ---


class TestStrategyGate:
    def setup_method(self):
        clear_pending_strategies()

    @pytest.mark.asyncio
    async def test_cheap_passes_through(self):
        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "cost_analysis": {"decision": "not_required", "analyses": []},
        }

        result = await strategy_gate(state, cb)
        assert result.get("optimization_state") is None

        types = [e.type for e in cb.get_events()]
        assert "strategy_gate/pass" in types

    @pytest.mark.asyncio
    async def test_expensive_pauses(self):
        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "cost_analysis": {
                "decision": "necessary",
                "analyses": [{"decision": "necessary", "reason": "Full scan"}],
            },
        }

        result = await strategy_gate(state, cb, session_id="test_session")
        assert result["optimization_state"] == "awaiting_strategy"
        assert "strategy" in result["response"].lower()

        types = [e.type for e in cb.get_events()]
        assert "strategy_gate/awaiting" in types

    def test_pending_strategy_save_and_retrieve(self):
        cb = CallbackManager()
        state: AgentState = {"question": "Test"}
        save_pending_strategy("test", state, cb)

        pending = get_pending_strategy("test")
        assert pending is not None
        assert pending.state["question"] == "Test"

    def test_pending_strategy_consume(self):
        cb = CallbackManager()
        state: AgentState = {"question": "Test"}
        save_pending_strategy("test", state, cb)

        pending = consume_pending_strategy("test")
        assert pending is not None

        # Second consume should return None
        assert consume_pending_strategy("test") is None

    def test_pending_strategy_not_found(self):
        assert get_pending_strategy("nonexistent") is None


# --- Submit Strategy MCP Tool Tests ---


class TestSubmitStrategy:
    def setup_method(self):
        clear_pending_strategies()

    def test_submit_sample(self):
        from mcpdb.mcp.tools.control import handle_control_tool

        cb = CallbackManager()
        state: AgentState = {"question": "Test"}
        save_pending_strategy("test", state, cb)

        result = handle_control_tool("submit_strategy", {
            "strategy": "SAMPLE",
            "session_id": "test",
        })
        assert "accepted" in result[0].text.lower() or "sample" in result[0].text.lower()

    def test_submit_cancel(self):
        from mcpdb.mcp.tools.control import handle_control_tool

        cb = CallbackManager()
        state: AgentState = {"question": "Test"}
        save_pending_strategy("test", state, cb)

        result = handle_control_tool("submit_strategy", {
            "strategy": "CANCEL",
            "session_id": "test",
        })
        assert "cancel" in result[0].text.lower()

    def test_submit_no_pending(self):
        from mcpdb.mcp.tools.control import handle_control_tool

        result = handle_control_tool("submit_strategy", {
            "strategy": "FULL",
            "session_id": "nonexistent",
        })
        assert "no pending" in result[0].text.lower() or "not found" in result[0].text.lower()

    def test_tool_registered(self):
        from mcpdb.mcp.tools.control import get_control_tools
        names = [t.name for t in get_control_tools()]
        assert "submit_strategy" in names


# --- LLM Cost Tracking Tests ---


class TestLLMCostTracking:
    def test_llm_usage_tracking(self):
        from mcpdb.llm.config import LLMUsage, TokenUsage

        usage = LLMUsage()
        usage.add("plan", TokenUsage(input_tokens=500, output_tokens=200))
        usage.add("synthesize", TokenUsage(input_tokens=300, output_tokens=100))

        assert usage.total_input_tokens == 800
        assert usage.total_output_tokens == 300
        assert usage.calls == 2
        assert len(usage.breakdown) == 2
