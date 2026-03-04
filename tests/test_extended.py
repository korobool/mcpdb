"""Tests for v1.3.0-v1.3.3 — Extended Mode.

Tests checkpoint, revise, reflect nodes and the extended subgraph.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, AsyncIterator

import pandas as pd
import pytest

from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.state import AgentState
from mcpdb.agent.nodes.extended import checkpoint, revise_plan, reflect
from mcpdb.agent.subgraphs.extended import run_extended
from mcpdb.agent.graph import run_agent
from mcpdb.llm.provider import LLMProvider, Message, StreamChunk
from mcpdb.llm.config import TokenUsage
from mcpdb.sources.registry import SourceRegistry
from mcpdb.sources.base import (
    ColumnInfo, QueryableSource, SourceMetadata, SourceType, TableInfo,
)


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


class SQLiteSource(QueryableSource):
    def __init__(self, db_path):
        self._db_path = db_path
        self._id = "test_db"

    @property
    def source_type(self):
        return SourceType.DATABASE

    def get_metadata(self):
        return SourceMetadata(
            source_id=self._id, source_type=SourceType.DATABASE,
            display_name="Test", tables=[
                TableInfo(name="metrics", columns=[
                    ColumnInfo(name="id", dtype="INTEGER"),
                    ColumnInfo(name="category", dtype="TEXT"),
                    ColumnInfo(name="value", dtype="REAL"),
                ], row_count=20),
            ], capabilities={"sql"},
        )

    def get_context_description(self):
        return "metrics table (id, category, value)"

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
    conn.execute("CREATE TABLE metrics (id INTEGER PRIMARY KEY, category TEXT, value REAL)")
    conn.executemany(
        "INSERT INTO metrics (category, value) VALUES (?, ?)",
        [("A", 10), ("B", 20), ("A", 30), ("B", 40), ("C", 50),
         ("A", 15), ("B", 25), ("C", 35), ("A", 45), ("B", 55),
         ("C", 60), ("A", 70), ("B", 80), ("C", 90), ("A", 100),
         ("B", 110), ("C", 120), ("A", 130), ("B", 140), ("C", 150)],
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def registry(test_db):
    reg = SourceRegistry()
    reg.add_source(SQLiteSource(test_db))
    yield reg
    reg.close_all()


# --- Checkpoint Tests ---


class TestCheckpoint:
    @pytest.mark.asyncio
    async def test_skip_before_interval(self):
        llm = MockLLM()
        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "plan": {"current_step_index": 1, "steps": [{"step_number": 1}] * 6},
        }

        result = await checkpoint(state, llm, cb, step_interval=3)
        assert result.get("checkpoint_action") == "continue"
        assert len(llm._responses) == 0  # No LLM call

    @pytest.mark.asyncio
    async def test_checkpoint_at_interval(self):
        llm = MockLLM()
        llm.queue({"action": "continue", "reason": "Good progress"})

        cb = CallbackManager()
        state: AgentState = {
            "question": "Comprehensive analysis",
            "plan": {
                "current_step_index": 3,
                "steps": [
                    {"step_number": 1, "description": "Step 1", "status": "success"},
                    {"step_number": 2, "description": "Step 2", "status": "success"},
                    {"step_number": 3, "description": "Step 3", "status": "success"},
                    {"step_number": 4, "description": "Step 4"},
                    {"step_number": 5, "description": "Step 5"},
                ],
            },
            "checkpoint_results": [],
        }

        result = await checkpoint(state, llm, cb, step_interval=3)
        assert result["checkpoint_action"] == "continue"
        assert len(result["checkpoint_results"]) == 1

        types = [e.type for e in cb.get_events()]
        assert "checkpoint/start" in types
        assert "checkpoint/complete" in types

    @pytest.mark.asyncio
    async def test_checkpoint_decides_done(self):
        llm = MockLLM()
        llm.queue({"action": "done", "reason": "We have enough data"})

        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "plan": {
                "current_step_index": 3,
                "steps": [{"step_number": i, "status": "success"} for i in range(6)],
            },
            "checkpoint_results": [],
        }

        result = await checkpoint(state, llm, cb, step_interval=3)
        assert result["checkpoint_action"] == "done"

    @pytest.mark.asyncio
    async def test_checkpoint_decides_revise(self):
        llm = MockLLM()
        llm.queue({"action": "revise", "reason": "Wrong approach", "revision_notes": "Try different grouping"})

        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "plan": {
                "current_step_index": 3,
                "steps": [{"step_number": i} for i in range(6)],
            },
            "checkpoint_results": [],
        }

        result = await checkpoint(state, llm, cb, step_interval=3)
        assert result["checkpoint_action"] == "revise"


# --- Revise Tests ---


class TestRevisePlan:
    @pytest.mark.asyncio
    async def test_revise_replaces_remaining_steps(self):
        llm = MockLLM()
        llm.queue({
            "steps": [
                {"step_number": 4, "action": "sql", "source_id": "test", "description": "New step", "code": "SELECT 1"},
            ],
        })

        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "source_context": "metrics table",
            "plan": {
                "current_step_index": 3,
                "steps": [
                    {"step_number": 1, "status": "success"},
                    {"step_number": 2, "status": "success"},
                    {"step_number": 3, "status": "success"},
                    {"step_number": 4, "description": "Old step"},
                    {"step_number": 5, "description": "Old step"},
                ],
            },
            "execution_log": [{"step_number": 1, "status": "success", "result_preview": "ok"}],
            "checkpoint_results": [{"reason": "Need revision"}],
        }

        result = await revise_plan(state, llm, cb)

        # Should have 3 completed + 1 new step
        assert len(result["plan"]["steps"]) == 4
        assert result["plan"]["steps"][3]["description"] == "New step"

        types = [e.type for e in cb.get_events()]
        assert "revise/start" in types
        assert "revise/ready" in types


# --- Reflect Tests ---


class TestReflect:
    @pytest.mark.asyncio
    async def test_reflect_produces_text(self):
        llm = MockLLM()
        llm.queue("The analysis revealed that category C has the highest values.")

        cb = CallbackManager()
        state: AgentState = {
            "question": "Analyze metrics by category",
            "execution_log": [
                {"step_number": 1, "action": "sql", "status": "success", "result_preview": "A: 400, B: 470, C: 505"},
            ],
        }

        result = await reflect(state, llm, cb)
        assert result["reflection"] is not None
        assert "category C" in result["reflection"]

        types = [e.type for e in cb.get_events()]
        assert "reflect/start" in types
        assert "reflect/ready" in types


# --- Extended Subgraph Tests ---


class TestExtendedSubgraph:
    @pytest.mark.asyncio
    async def test_full_extended_flow(self, registry):
        """Plan → execute 2 steps → reflect → validate → synthesize."""
        llm = MockLLM()
        # Plan
        llm.queue({
            "analysis": "Category analysis",
            "approach": "Two queries",
            "steps": [
                {"step_number": 1, "action": "sql", "source_id": "test_db",
                 "description": "Count by category",
                 "code": "SELECT category, COUNT(*) as cnt FROM metrics GROUP BY category"},
                {"step_number": 2, "action": "sql", "source_id": "test_db",
                 "description": "Sum by category",
                 "code": "SELECT category, SUM(value) as total FROM metrics GROUP BY category"},
            ],
        })
        # Reflect
        llm.queue("Category C has the highest total value. All categories have roughly equal counts.")
        # Validate
        llm.queue({"result": "adequate"})
        # Synthesize
        llm.queue("Category analysis shows A, B, C each have ~6-7 entries. C leads in total value.")

        cb = CallbackManager()
        state: AgentState = {
            "question": "Analyze metrics by category",
            "source_context": "metrics table",
            "replan_count": 0,
            "execution_log": [],
            "artifacts": [],
            "max_retries": 3,
            "checkpoint_results": [],
        }

        result = await run_extended(state, llm, cb, registry)

        assert result["response"] is not None
        assert result["reflection"] is not None
        assert len(result["execution_log"]) == 2

        types = [e.type for e in cb.get_events()]
        assert "extended/start" in types
        assert "reflect/start" in types
        assert "extended/complete" in types

    @pytest.mark.asyncio
    async def test_extended_via_orchestrator(self, registry):
        """run_agent with mode_override='extended' runs extended pipeline."""
        llm = MockLLM()
        # Plan
        llm.queue({
            "analysis": "Count",
            "approach": "SQL",
            "steps": [{"step_number": 1, "action": "sql", "source_id": "test_db",
                        "description": "Count", "code": "SELECT COUNT(*) as cnt FROM metrics"}],
        })
        # Reflect
        llm.queue("Simple count analysis.")
        # Validate
        llm.queue({"result": "adequate"})
        # Synthesize
        llm.queue("There are 20 metrics records.")

        cb = CallbackManager()
        result = await run_agent(
            question="How many metrics?",
            registry=registry,
            llm=llm,
            callbacks=cb,
            mode_override="extended",
        )

        assert result["response"] is not None
        types = [e.type for e in cb.get_events()]
        assert "extended/start" in types
