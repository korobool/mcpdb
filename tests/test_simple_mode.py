"""Tests for v0.4.0-v0.4.6 — Simple Mode (Core Execution Loop).

Tests plan, execute, debug, synthesize, validate, replan nodes
and the full simple subgraph pipeline.
Uses MockLLM and real SQLite for execution.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator

import pandas as pd
import pytest

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.nodes.common import make_plan, execute_step, debug_step, synthesize
from mcpdb.agent.nodes.validators import validate_result, replan
from mcpdb.agent.subgraphs.simple import run_simple
from mcpdb.agent.graph import run_agent
from mcpdb.llm.provider import LLMProvider, Message, StreamChunk
from mcpdb.llm.config import TokenUsage
from mcpdb.sources.registry import SourceRegistry
from mcpdb.sources.base import SourceType, SourceMetadata, TableInfo, ColumnInfo, QueryableSource


# --- Multi-response MockLLM ---


class MockLLM(LLMProvider):
    """LLM that returns queued responses in order."""

    def __init__(self):
        self._responses: list[dict[str, Any] | str] = []
        self._call_index = 0
        self.calls: list[dict[str, Any]] = []

    def queue(self, *responses: dict[str, Any] | str) -> None:
        """Queue responses to be returned in order."""
        self._responses.extend(responses)

    async def stream(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        self.calls.append({
            "messages": [m.content[:100] for m in messages],
            "system": system,
            "max_tokens": max_tokens,
        })

        if self._call_index < len(self._responses):
            resp = self._responses[self._call_index]
        else:
            resp = {"error": "no more queued responses"}
        self._call_index += 1

        text = resp if isinstance(resp, str) else json.dumps(resp)
        yield StreamChunk(text=text)
        yield StreamChunk(text="", usage=TokenUsage(input_tokens=100, output_tokens=50))


# --- Real SQLite queryable source ---


class SQLiteTestSource(QueryableSource):
    """Real queryable source backed by SQLite for testing execution."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._id = "test_sqlite"

    @property
    def source_type(self) -> SourceType:
        return SourceType.DATABASE

    def get_metadata(self) -> SourceMetadata:
        return SourceMetadata(
            source_id=self._id,
            source_type=SourceType.DATABASE,
            display_name="Test SQLite",
            tables=[
                TableInfo(name="customers", columns=[
                    ColumnInfo(name="id", dtype="INTEGER"),
                    ColumnInfo(name="name", dtype="TEXT"),
                    ColumnInfo(name="revenue", dtype="REAL"),
                ], row_count=5),
            ],
            capabilities={"sql"},
        )

    def get_context_description(self) -> str:
        return (
            "Source: test_sqlite (SQLite)\n"
            "Table: customers (5 rows)\n"
            "  - id INTEGER (PK)\n"
            "  - name TEXT\n"
            "  - revenue REAL"
        )

    def execute_query(self, query: str, max_rows: int = 100) -> pd.DataFrame:
        conn = sqlite3.connect(self._db_path)
        try:
            df = pd.read_sql_query(query, conn)
            return df.head(max_rows)
        finally:
            conn.close()

    def get_sample(self, table_name: str, limit: int = 5) -> pd.DataFrame:
        return self.execute_query(f"SELECT * FROM {table_name} LIMIT {limit}")

    def close(self) -> None:
        pass


@pytest.fixture
def test_db(tmp_path):
    """Create a test SQLite database with sample data."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, revenue REAL)"
    )
    conn.executemany(
        "INSERT INTO customers (name, revenue) VALUES (?, ?)",
        [
            ("Alice", 1500.0),
            ("Bob", 2300.0),
            ("Charlie", 800.0),
            ("Diana", 3100.0),
            ("Eve", 1200.0),
        ],
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def registry_with_source(test_db):
    """Registry with a real SQLite source."""
    reg = SourceRegistry()
    reg.add_source(SQLiteTestSource(test_db))
    yield reg
    reg.close_all()


# --- Plan Node Tests ---


class TestPlanNode:
    @pytest.mark.asyncio
    async def test_make_plan_creates_steps(self, registry_with_source):
        llm = MockLLM()
        llm.queue({
            "analysis": "User wants top customers by revenue",
            "approach": "Query customers ordered by revenue",
            "steps": [
                {
                    "step_number": 1,
                    "action": "sql",
                    "source_id": "test_sqlite",
                    "description": "Get top customers",
                    "code": "SELECT name, revenue FROM customers ORDER BY revenue DESC",
                },
            ],
        })

        cb = CallbackManager()
        state: AgentState = {
            "question": "Show top customers by revenue",
            "source_context": "customers table with name and revenue",
        }

        result = await make_plan(state, llm, cb, registry_with_source)

        assert "plan" in result
        assert len(result["plan"]["steps"]) == 1
        assert result["plan"]["steps"][0]["status"] == "pending"
        assert result["plan"]["steps"][0]["attempts"] == 0
        assert result["plan"]["current_step_index"] == 0

        types = [e.type for e in cb.get_events()]
        assert "plan/start" in types
        assert "plan/ready" in types

    @pytest.mark.asyncio
    async def test_make_plan_fallback_on_error(self, registry_with_source):
        """Plan node falls back gracefully when LLM returns bad JSON."""
        llm = MockLLM()
        llm.queue("this is not valid json {{{")

        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "source_context": "...",
        }

        result = await make_plan(state, llm, cb, registry_with_source)
        # With a registry that has sources, fallback generates EDA steps
        assert result["plan"]["approach"] == "fallback_eda"
        assert len(result["plan"]["steps"]) > 0


# --- Execute Node Tests ---


class TestExecuteNode:
    @pytest.mark.asyncio
    async def test_execute_sql_step(self, registry_with_source):
        cb = CallbackManager()
        state: AgentState = {
            "question": "Top customers",
            "plan": {
                "analysis": "test",
                "approach": "test",
                "current_step_index": 0,
                "steps": [{
                    "step_number": 1,
                    "action": "sql",
                    "source_id": "test_sqlite",
                    "code": "SELECT name, revenue FROM customers ORDER BY revenue DESC LIMIT 3",
                    "status": "pending",
                    "attempts": 0,
                }],
            },
            "execution_log": [],
            "artifacts": [],
        }

        result = await execute_step(state, cb, registry_with_source)

        assert result["plan"]["current_step_index"] == 1
        assert result["plan"]["steps"][0]["status"] == "success"
        assert result["current_error"] is None
        assert len(result["execution_log"]) == 1
        assert result["execution_log"][0]["status"] == "success"
        assert len(result["artifacts"]) == 1
        assert result["artifacts"][0]["type"] == "table"

        # Verify actual data
        df = result["last_result"]["dataframe"]
        assert len(df) == 3
        assert df.iloc[0]["name"] == "Diana"  # Highest revenue

    @pytest.mark.asyncio
    async def test_execute_step_error(self, registry_with_source):
        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "plan": {
                "current_step_index": 0,
                "steps": [{
                    "step_number": 1,
                    "action": "sql",
                    "source_id": "test_sqlite",
                    "code": "SELECT * FROM nonexistent_table",
                    "status": "pending",
                    "attempts": 0,
                }],
            },
            "execution_log": [],
            "artifacts": [],
        }

        result = await execute_step(state, cb, registry_with_source)

        assert result["current_error"] is not None
        assert result["current_error"]["step_index"] == 0
        assert "nonexistent_table" in result["current_error"]["error"].lower() or "no such table" in result["current_error"]["error"].lower()
        assert len(result["execution_log"]) == 1
        assert result["execution_log"][0]["status"] == "error"

    @pytest.mark.asyncio
    async def test_execute_schema_step(self, registry_with_source):
        cb = CallbackManager()
        state: AgentState = {
            "question": "Show schema",
            "plan": {
                "current_step_index": 0,
                "steps": [{
                    "step_number": 1,
                    "action": "schema",
                    "source_id": "test_sqlite",
                    "code": "",
                    "status": "pending",
                    "attempts": 0,
                }],
            },
            "execution_log": [],
            "artifacts": [],
        }

        result = await execute_step(state, cb, registry_with_source)
        assert result["plan"]["steps"][0]["status"] == "success"
        assert "test_sqlite" in result["last_result"]["output"].lower() or "customers" in result["last_result"]["output"].lower()

    @pytest.mark.asyncio
    async def test_execute_sample_step(self, registry_with_source):
        cb = CallbackManager()
        state: AgentState = {
            "question": "Show sample",
            "plan": {
                "current_step_index": 0,
                "steps": [{
                    "step_number": 1,
                    "action": "sample",
                    "source_id": "test_sqlite",
                    "table": "customers",
                    "code": "customers",
                    "status": "pending",
                    "attempts": 0,
                }],
            },
            "execution_log": [],
            "artifacts": [],
        }

        result = await execute_step(state, cb, registry_with_source)
        assert result["plan"]["steps"][0]["status"] == "success"

    @pytest.mark.asyncio
    async def test_execute_no_source_uses_first(self, registry_with_source):
        """When source_id is None, falls back to first queryable source."""
        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "plan": {
                "current_step_index": 0,
                "steps": [{
                    "step_number": 1,
                    "action": "sql",
                    "source_id": None,
                    "code": "SELECT COUNT(*) as cnt FROM customers",
                    "status": "pending",
                    "attempts": 0,
                }],
            },
            "execution_log": [],
            "artifacts": [],
        }

        result = await execute_step(state, cb, registry_with_source)
        assert result["plan"]["steps"][0]["status"] == "success"
        assert result["last_result"]["row_count"] == 1


# --- Debug Node Tests ---


class TestDebugNode:
    @pytest.mark.asyncio
    async def test_debug_fixes_code(self):
        llm = MockLLM()
        llm.queue({
            "error_analysis": "Table name was wrong",
            "corrected_code": "SELECT * FROM customers",
        })

        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "source_context": "customers table",
            "plan": {
                "steps": [{
                    "step_number": 1,
                    "action": "sql",
                    "code": "SELECT * FROM custoemrs",
                    "status": "error",
                    "attempts": 1,
                }],
            },
            "current_error": {
                "step_index": 0,
                "action": "sql",
                "code": "SELECT * FROM custoemrs",
                "error": "no such table: custoemrs",
                "attempts": 1,
            },
            "max_retries": 3,
        }

        result = await debug_step(state, llm, cb)

        assert result["current_error"] is None
        assert result["plan"]["steps"][0]["code"] == "SELECT * FROM customers"
        assert result["plan"]["steps"][0]["status"] == "pending"

        types = [e.type for e in cb.get_events()]
        assert "debug/start" in types
        assert "debug/fixed" in types

    @pytest.mark.asyncio
    async def test_debug_gives_up_after_max_retries(self):
        llm = MockLLM()
        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "plan": {
                "steps": [{
                    "step_number": 1,
                    "action": "sql",
                    "code": "broken",
                    "status": "error",
                    "attempts": 3,
                }],
                "current_step_index": 0,
            },
            "current_error": {
                "step_index": 0,
                "action": "sql",
                "code": "broken",
                "error": "syntax error",
                "attempts": 3,
            },
            "max_retries": 3,
        }

        result = await debug_step(state, llm, cb)

        assert result["current_error"] is None
        assert result["plan"]["steps"][0]["status"] == "failed"
        assert result["plan"]["current_step_index"] == 1  # Skipped to next

        types = [e.type for e in cb.get_events()]
        assert "debug/give_up" in types

    @pytest.mark.asyncio
    async def test_debug_no_error_returns_unchanged(self):
        llm = MockLLM()
        cb = CallbackManager()
        state: AgentState = {"question": "Test", "current_error": None}

        result = await debug_step(state, llm, cb)
        assert result is state  # Unchanged


# --- Synthesize Node Tests ---


class TestSynthesizeNode:
    @pytest.mark.asyncio
    async def test_synthesize_produces_response(self):
        llm = MockLLM()
        llm.queue({"code": "for row in artifacts[0]['data']['rows']:\n    print(f'{row[0]}: ${row[1]:,.2f}')"})

        cb = CallbackManager()
        state: AgentState = {
            "question": "Who is the top customer?",
            "execution_log": [{
                "step_number": 1,
                "action": "sql",
                "status": "success",
                "result_summary": "1 rows x 2 columns",
            }],
            "artifacts": [{
                "type": "table",
                "title": "Top customers",
                "data": {"columns": ["name", "revenue"], "rows": [["Diana", 3100.0]], "total_rows": 1},
            }],
        }

        result = await synthesize(state, llm, cb)
        assert "Diana" in result["response"]

        types = [e.type for e in cb.get_events()]
        assert "synthesize/start" in types
        assert "synthesize/complete" in types

    @pytest.mark.asyncio
    async def test_synthesize_handles_no_results(self):
        llm = MockLLM()
        llm.queue({"code": "print('No data was available to answer this question.')"})

        cb = CallbackManager()
        state: AgentState = {
            "question": "Anything?",
            "execution_log": [],
            "artifacts": [],
        }

        result = await synthesize(state, llm, cb)
        assert result["response"] is not None


# --- Validate Node Tests ---


class TestValidateNode:
    @pytest.mark.asyncio
    async def test_validate_adequate(self):
        llm = MockLLM()
        llm.queue({"result": "adequate"})

        cb = CallbackManager()
        state: AgentState = {
            "question": "Top customers?",
            "execution_log": [{"step_number": 1, "status": "success", "result_summary": "Diana 3100"}],
            "replan_count": 0,
        }

        result = await validate_result(state, llm, cb)
        assert result["validation_result"] == "adequate"

    @pytest.mark.asyncio
    async def test_validate_inadequate(self):
        llm = MockLLM()
        llm.queue({"result": "inadequate", "reason": "Missing revenue breakdown"})

        cb = CallbackManager()
        state: AgentState = {
            "question": "Revenue breakdown by month?",
            "execution_log": [{"step_number": 1, "status": "success", "result_summary": "total: 8900"}],
            "replan_count": 0,
        }

        result = await validate_result(state, llm, cb)
        assert result["validation_result"] == "inadequate"
        assert result["validation_reason"] == "Missing revenue breakdown"

    @pytest.mark.asyncio
    async def test_validate_skips_after_replan(self):
        llm = MockLLM()
        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "execution_log": [],
            "replan_count": 1,
        }

        result = await validate_result(state, llm, cb)
        assert result["validation_result"] == "adequate"
        assert len(llm.calls) == 0  # No LLM call made


# --- Replan Node Tests ---


class TestReplanNode:
    @pytest.mark.asyncio
    async def test_replan_creates_new_plan(self):
        llm = MockLLM()
        llm.queue({
            "analysis": "Need monthly breakdown",
            "approach": "Group by month",
            "steps": [
                {
                    "step_number": 1,
                    "action": "sql",
                    "source_id": "test_sqlite",
                    "description": "Monthly revenue",
                    "code": "SELECT strftime('%Y-%m', date) as month, SUM(revenue) FROM orders GROUP BY 1",
                },
            ],
        })

        cb = CallbackManager()
        state: AgentState = {
            "question": "Revenue by month?",
            "source_context": "orders table",
            "execution_log": [{"step_number": 1, "status": "success", "result_summary": "total: 8900"}],
            "validation_reason": "Missing monthly breakdown",
            "replan_count": 0,
        }

        result = await replan(state, llm, cb)

        assert result["replan_count"] == 1
        assert len(result["plan"]["steps"]) == 1
        assert result["plan"]["current_step_index"] == 0
        assert result["current_error"] is None
        assert result["validation_result"] is None

        types = [e.type for e in cb.get_events()]
        assert "replan/start" in types
        assert "replan/ready" in types


# --- Simple Subgraph Integration Tests ---


class TestSimpleSubgraph:
    @pytest.mark.asyncio
    async def test_full_simple_flow(self, registry_with_source):
        """Plan → execute → validate (adequate) → synthesize."""
        llm = MockLLM()
        # 1. Plan
        llm.queue({
            "analysis": "Top customers by revenue",
            "approach": "SQL query",
            "steps": [{
                "step_number": 1,
                "action": "sql",
                "source_id": "test_sqlite",
                "description": "Get top customers",
                "code": "SELECT name, revenue FROM customers ORDER BY revenue DESC LIMIT 3",
            }],
        })
        # 2. Validate (adequate)
        llm.queue({"result": "adequate"})
        # 3. Synthesize (now expects JSON with code that formats the answer)
        llm.queue({"code": "for row in artifacts[0]['data']['rows']:\n    print(f\"{row[0]}: ${row[1]:,.2f}\")"})

        cb = CallbackManager()
        state: AgentState = {
            "question": "Show top 3 customers by revenue",
            "source_context": registry_with_source.get_combined_context(),
            "active_source_ids": ["test_sqlite"],
            "replan_count": 0,
            "execution_log": [],
            "artifacts": [],
            "max_retries": 3,
        }

        result = await run_simple(state, llm, cb, registry_with_source)

        assert result["response"] is not None
        assert "Diana" in result["response"]
        assert len(result["execution_log"]) == 1
        assert result["execution_log"][0]["status"] == "success"

        types = [e.type for e in cb.get_events()]
        assert "simple/start" in types
        assert "plan/start" in types
        assert "step/start" in types
        assert "step/complete" in types
        assert "validate/start" in types
        assert "synthesize/start" in types
        assert "simple/complete" in types

    @pytest.mark.asyncio
    async def test_simple_with_debug_retry(self, registry_with_source):
        """Plan → execute (fail) → debug → execute (succeed) → validate → synthesize."""
        llm = MockLLM()
        # 1. Plan (with typo in SQL)
        llm.queue({
            "analysis": "Count customers",
            "approach": "SQL count",
            "steps": [{
                "step_number": 1,
                "action": "sql",
                "source_id": "test_sqlite",
                "description": "Count",
                "code": "SELECT COUNT(*) FROM custoemrs",  # Typo
            }],
        })
        # 2. Debug (fix the typo)
        llm.queue({
            "error_analysis": "Typo in table name",
            "corrected_code": "SELECT COUNT(*) as cnt FROM customers",
        })
        # 3. Validate
        llm.queue({"result": "adequate"})
        # 4. Synthesize
        llm.queue({"code": "print('There are 5 customers in the database.')"})

        cb = CallbackManager()
        state: AgentState = {
            "question": "How many customers?",
            "source_context": "customers table",
            "replan_count": 0,
            "execution_log": [],
            "artifacts": [],
            "max_retries": 3,
        }

        result = await run_simple(state, llm, cb, registry_with_source)

        assert result["response"] is not None
        assert "5" in result["response"]

        # Check we had an error then success
        statuses = [e["status"] for e in result["execution_log"]]
        assert "error" in statuses
        assert "success" in statuses

    @pytest.mark.asyncio
    async def test_simple_with_replan(self, registry_with_source):
        """Plan → execute → validate (inadequate) → replan → execute → synthesize."""
        llm = MockLLM()
        # 1. First plan
        llm.queue({
            "analysis": "Customer names",
            "approach": "Query",
            "steps": [{
                "step_number": 1,
                "action": "sql",
                "source_id": "test_sqlite",
                "description": "Get names",
                "code": "SELECT name FROM customers",
            }],
        })
        # 2. Validate (inadequate — missing revenue)
        llm.queue({"result": "inadequate", "reason": "Missing revenue data"})
        # 3. Replan
        llm.queue({
            "analysis": "Need revenue too",
            "approach": "Include revenue",
            "steps": [{
                "step_number": 1,
                "action": "sql",
                "source_id": "test_sqlite",
                "description": "Get names and revenue",
                "code": "SELECT name, revenue FROM customers ORDER BY revenue DESC",
            }],
        })
        # 4. Synthesize (validation skipped after replan)
        llm.queue({"code": "print('Here are the customers with revenue: Diana ($3,100), Bob ($2,300), ...')"})

        cb = CallbackManager()
        state: AgentState = {
            "question": "Show customers with revenue",
            "source_context": "customers table with name and revenue columns",
            "replan_count": 0,
            "execution_log": [],
            "artifacts": [],
            "max_retries": 3,
        }

        result = await run_simple(state, llm, cb, registry_with_source)

        assert result["response"] is not None
        assert result["replan_count"] == 1

        types = [e.type for e in cb.get_events()]
        assert "validate/inadequate" in types
        assert "replan/start" in types

    @pytest.mark.asyncio
    async def test_simple_empty_plan(self, registry_with_source):
        """If LLM plan fails, agent still produces a response via fallback."""
        llm = MockLLM()
        llm.queue("not valid json {{")  # Force plan failure

        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "source_context": "...",
            "replan_count": 0,
            "execution_log": [],
            "artifacts": [],
            "max_retries": 3,
        }

        result = await run_simple(state, llm, cb, registry_with_source)
        # Agent should still produce a response (fallback plan or context synthesis)
        assert result["response"] is not None
        assert len(result["response"]) > 0

    @pytest.mark.asyncio
    async def test_multi_step_execution(self, registry_with_source):
        """Plan with 2 steps, both execute successfully."""
        llm = MockLLM()
        llm.queue({
            "analysis": "Revenue stats",
            "approach": "Two queries",
            "steps": [
                {
                    "step_number": 1,
                    "action": "sql",
                    "source_id": "test_sqlite",
                    "description": "Total revenue",
                    "code": "SELECT SUM(revenue) as total FROM customers",
                },
                {
                    "step_number": 2,
                    "action": "sql",
                    "source_id": "test_sqlite",
                    "description": "Average revenue",
                    "code": "SELECT AVG(revenue) as avg_rev FROM customers",
                },
            ],
        })
        # Validate
        llm.queue({"result": "adequate"})
        # Synthesize
        llm.queue({"code": "print('Total revenue is $8,900 with an average of $1,780 per customer.')"})

        cb = CallbackManager()
        state: AgentState = {
            "question": "Revenue statistics",
            "source_context": "customers table",
            "replan_count": 0,
            "execution_log": [],
            "artifacts": [],
            "max_retries": 3,
        }

        result = await run_simple(state, llm, cb, registry_with_source)

        assert len(result["execution_log"]) == 2
        assert all(e["status"] == "success" for e in result["execution_log"])
        assert "$8,900" in result["response"] or "8900" in result["response"] or "8,900" in result["response"]


# --- Orchestrator Integration Tests ---


class TestOrchestratorSimpleMode:
    @pytest.mark.asyncio
    async def test_agent_simple_mode_override(self, registry_with_source):
        """run_agent with mode_override='simple' runs the full simple pipeline."""
        llm = MockLLM()
        # Plan
        llm.queue({
            "analysis": "Count",
            "approach": "SQL",
            "steps": [{
                "step_number": 1,
                "action": "sql",
                "source_id": "test_sqlite",
                "description": "Count customers",
                "code": "SELECT COUNT(*) as cnt FROM customers",
            }],
        })
        # Validate
        llm.queue({"result": "adequate"})
        # Synthesize
        llm.queue({"code": "print('There are 5 customers.')"})

        cb = CallbackManager()
        result = await run_agent(
            question="How many customers?",
            registry=registry_with_source,
            llm=llm,
            callbacks=cb,
            mode_override="simple",
        )

        assert result["response"] is not None
        assert "5" in result["response"]

        types = [e.type for e in cb.get_events()]
        assert "classify/override" in types
        assert "simple/start" in types
        assert "agent/complete" in types

    @pytest.mark.asyncio
    async def test_quick_escalation_to_simple(self, registry_with_source):
        """Quick mode escalates to simple when data execution is needed."""
        llm = MockLLM()
        # Classify → quick
        llm.queue({
            "mode": "quick",
            "reasoning": "Looks like a schema question",
            "target_sources": ["test_sqlite"],
            "key_entities": ["customers"],
        })
        # Quick → escalate (plain text triggers escalation)
        llm.queue("ESCALATE")
        # Simple: Plan
        llm.queue({
            "analysis": "Top customers",
            "approach": "SQL",
            "steps": [{
                "step_number": 1,
                "action": "sql",
                "source_id": "test_sqlite",
                "description": "Top customers",
                "code": "SELECT name, revenue FROM customers ORDER BY revenue DESC LIMIT 3",
            }],
        })
        # Simple: Validate
        llm.queue({"result": "adequate"})
        # Simple: Synthesize
        llm.queue({"code": "print('Top 3 customers: Diana, Bob, Alice.')"})

        cb = CallbackManager()
        result = await run_agent(
            question="Show top 3 customers",
            registry=registry_with_source,
            llm=llm,
            callbacks=cb,
        )

        assert result["response"] is not None
        assert result["query_mode"] == "simple"

        types = [e.type for e in cb.get_events()]
        assert "quick/escalate" in types
        assert "simple/start" in types
