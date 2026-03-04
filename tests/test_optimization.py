"""Tests for v1.2.0-v1.2.1 — Optimization Mode.

Tests optimize_plan node and the optimization subgraph.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, AsyncIterator

import pandas as pd
import pytest

from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.state import AgentState
from mcpdb.agent.nodes.optimize import optimize_plan, _generic_limit_fallback
from mcpdb.agent.subgraphs.optimization import run_optimization
from mcpdb.llm.provider import LLMProvider, Message, StreamChunk
from mcpdb.llm.config import TokenUsage
from mcpdb.sources.registry import SourceRegistry
from mcpdb.sources.base import (
    ColumnInfo, QueryableSource, SourceMetadata, SourceType, TableInfo,
)


# --- MockLLM ---

class MockLLM(LLMProvider):
    def __init__(self):
        self._responses = []
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


# --- SQLite source ---

class SQLiteTestSource(QueryableSource):
    def __init__(self, db_path):
        self._db_path = db_path
        self._id = "test_sqlite"

    @property
    def source_type(self):
        return SourceType.DATABASE

    def get_metadata(self):
        return SourceMetadata(
            source_id=self._id,
            source_type=SourceType.DATABASE,
            display_name="Test",
            tables=[
                TableInfo(name="sales", columns=[
                    ColumnInfo(name="id", dtype="INTEGER"),
                    ColumnInfo(name="amount", dtype="REAL"),
                ], row_count=100),
            ],
            capabilities={"sql"},
        )

    def get_context_description(self):
        return "sales table (id, amount)"

    def execute_query(self, query, max_rows=100):
        conn = sqlite3.connect(self._db_path)
        try:
            return pd.read_sql_query(query, conn).head(max_rows)
        finally:
            conn.close()

    def get_sample(self, table_name, limit=5):
        return self.execute_query(f"SELECT * FROM {table_name} LIMIT {limit}")

    def close(self):
        pass


@pytest.fixture
def test_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE sales (id INTEGER PRIMARY KEY, amount REAL)")
    conn.executemany(
        "INSERT INTO sales (amount) VALUES (?)",
        [(i * 10.5,) for i in range(100)],
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def registry(test_db):
    reg = SourceRegistry()
    reg.add_source(SQLiteTestSource(test_db))
    yield reg
    reg.close_all()


# --- Optimize Plan Node Tests ---


class TestOptimizePlan:
    @pytest.mark.asyncio
    async def test_full_strategy_keeps_original(self, registry):
        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "strategy_choice": "FULL",
            "plan": {
                "steps": [{
                    "action": "sql",
                    "source_id": "test_sqlite",
                    "code": "SELECT * FROM sales",
                }],
            },
        }

        result = await optimize_plan(state, cb, registry)
        assert result["optimization_state"] == "full"
        assert result["plan"]["steps"][0]["code"] == "SELECT * FROM sales"

    @pytest.mark.asyncio
    async def test_cancel_strategy(self, registry):
        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "strategy_choice": "CANCEL",
            "plan": {"steps": [{"action": "sql", "code": "SELECT * FROM sales"}]},
        }

        result = await optimize_plan(state, cb, registry)
        assert result["optimization_state"] == "cancelled"
        assert "cancel" in result["response"].lower()

    @pytest.mark.asyncio
    async def test_sample_strategy_adds_limit(self, registry):
        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "strategy_choice": "SAMPLE",
            "plan": {
                "steps": [{
                    "action": "sql",
                    "source_id": "test_sqlite",
                    "code": "SELECT * FROM sales",
                    "status": "pending",
                }],
            },
        }

        result = await optimize_plan(state, cb, registry)
        assert result["optimization_state"] == "sampled"
        # The SQL should have been modified
        modified_code = result["plan"]["steps"][0]["code"]
        assert modified_code != "SELECT * FROM sales"

    @pytest.mark.asyncio
    async def test_sample_skips_non_sql(self, registry):
        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "strategy_choice": "SAMPLE",
            "plan": {
                "steps": [
                    {"action": "python", "code": "print('hello')"},
                    {"action": "sql", "source_id": "test_sqlite", "code": "SELECT * FROM sales"},
                ],
            },
        }

        result = await optimize_plan(state, cb, registry)
        # Python step unchanged
        assert result["plan"]["steps"][0]["code"] == "print('hello')"

    @pytest.mark.asyncio
    async def test_sample_preserves_existing_limit(self, registry):
        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "strategy_choice": "SAMPLE",
            "plan": {
                "steps": [{
                    "action": "sql",
                    "source_id": "test_sqlite",
                    "code": "SELECT * FROM sales LIMIT 10",
                }],
            },
        }

        result = await optimize_plan(state, cb, registry)
        # Already has LIMIT, generic fallback should not double-add
        code = result["plan"]["steps"][0]["code"]
        assert code.count("LIMIT") == 1


class TestGenericLimitFallback:
    def test_adds_limit(self):
        result = _generic_limit_fallback("SELECT * FROM orders")
        assert "LIMIT 10000" in result

    def test_preserves_existing_limit(self):
        result = _generic_limit_fallback("SELECT * FROM orders LIMIT 5")
        assert result == "SELECT * FROM orders LIMIT 5"

    def test_strips_trailing_semicolon(self):
        result = _generic_limit_fallback("SELECT * FROM orders;")
        assert "LIMIT 10000" in result
        assert not result.endswith(";LIMIT")


# --- Optimization Subgraph Tests ---


class TestOptimizationSubgraph:
    @pytest.mark.asyncio
    async def test_cheap_query_skips_gate(self, registry):
        """Cheap query passes cost check and executes directly."""
        llm = MockLLM()
        # Plan
        llm.queue({
            "analysis": "Sum sales",
            "approach": "SQL",
            "steps": [{
                "step_number": 1,
                "action": "sql",
                "source_id": "test_sqlite",
                "description": "Total sales",
                "code": "SELECT SUM(amount) as total FROM sales LIMIT 1",
            }],
        })
        # Synthesize
        llm.queue("Total sales amount is $4,950.")

        cb = CallbackManager()
        state: AgentState = {
            "question": "Total sales?",
            "source_context": "sales table",
            "replan_count": 0,
            "execution_log": [],
            "artifacts": [],
            "max_retries": 3,
        }

        result = await run_optimization(state, llm, cb, registry)
        assert result["response"] is not None
        assert result.get("optimization_state") != "awaiting_strategy"

        types = [e.type for e in cb.get_events()]
        assert "optimization/start" in types
        assert "cost_check/start" in types
        assert "optimization/complete" in types

    @pytest.mark.asyncio
    async def test_full_flow_with_strategy(self, registry):
        """Test optimization with pre-set FULL strategy (no interactive gate)."""
        llm = MockLLM()
        # Plan
        llm.queue({
            "analysis": "Total",
            "approach": "SQL",
            "steps": [{
                "step_number": 1,
                "action": "sql",
                "source_id": "test_sqlite",
                "description": "Count",
                "code": "SELECT COUNT(*) as cnt FROM sales LIMIT 1",
            }],
        })
        # Synthesize
        llm.queue("There are 100 sales records.")

        cb = CallbackManager()
        state: AgentState = {
            "question": "How many sales?",
            "source_context": "sales table",
            "strategy_choice": "FULL",
            "replan_count": 0,
            "execution_log": [],
            "artifacts": [],
            "max_retries": 3,
        }

        result = await run_optimization(state, llm, cb, registry)
        assert "100" in result["response"]
