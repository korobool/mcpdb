"""Tests for v0.5.0-v0.5.3 — Python Sandbox.

Tests security validation, subprocess execution, DataFrame/chart capture,
and integration with the execute node.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, AsyncIterator

import pandas as pd
import pytest

from mcpdb.sandbox.security import validate_imports, ALLOWED_MODULES, BLOCKED_MODULES
from mcpdb.sandbox.executor import execute_python, SandboxResult


# --- Security: Import Validation ---


class TestImportValidation:
    def test_allowed_import_pandas(self):
        assert validate_imports("import pandas") == []

    def test_allowed_import_numpy(self):
        assert validate_imports("import numpy as np") == []

    def test_allowed_import_json(self):
        assert validate_imports("import json") == []

    def test_allowed_import_math(self):
        assert validate_imports("import math") == []

    def test_allowed_import_re(self):
        assert validate_imports("import re") == []

    def test_allowed_import_datetime(self):
        assert validate_imports("import datetime") == []

    def test_allowed_from_import(self):
        assert validate_imports("from collections import Counter") == []

    def test_allowed_matplotlib_pyplot(self):
        assert validate_imports("import matplotlib.pyplot as plt") == []

    def test_blocked_import_os(self):
        violations = validate_imports("import os")
        assert len(violations) == 1
        assert "os" in violations[0]

    def test_blocked_import_subprocess(self):
        violations = validate_imports("import subprocess")
        assert len(violations) == 1
        assert "subprocess" in violations[0]

    def test_blocked_import_sys(self):
        violations = validate_imports("import sys")
        assert len(violations) == 1

    def test_blocked_import_socket(self):
        violations = validate_imports("import socket")
        assert len(violations) == 1

    def test_blocked_from_os_path(self):
        violations = validate_imports("from os.path import join")
        assert len(violations) == 1

    def test_blocked_import_shutil(self):
        violations = validate_imports("import shutil")
        assert len(violations) == 1

    def test_blocked_import_pathlib(self):
        violations = validate_imports("import pathlib")
        assert len(violations) == 1

    def test_multiple_violations(self):
        code = "import os\nimport subprocess\nimport sys"
        violations = validate_imports(code)
        assert len(violations) == 3

    def test_no_imports(self):
        assert validate_imports("x = 1 + 2") == []

    def test_syntax_error_passes(self):
        """Syntax errors are not import violations — executor handles them."""
        assert validate_imports("def foo(") == []

    def test_blocked_http(self):
        violations = validate_imports("import http.client")
        assert len(violations) == 1

    def test_blocked_urllib(self):
        violations = validate_imports("import urllib.request")
        assert len(violations) == 1


# --- Executor: Basic Execution ---


class TestExecutorBasic:
    def test_simple_print(self):
        result = execute_python("print(1 + 1)")
        assert result.success
        assert "2" in result.stdout

    def test_multiline_code(self):
        code = "x = 10\ny = 20\nprint(x + y)"
        result = execute_python(code)
        assert result.success
        assert "30" in result.stdout

    def test_syntax_error(self):
        result = execute_python("def foo(")
        assert not result.success
        assert result.error is not None
        assert "SyntaxError" in result.error or "syntax" in result.error.lower()

    def test_runtime_error(self):
        result = execute_python("x = 1 / 0")
        assert not result.success
        assert "ZeroDivisionError" in result.error

    def test_import_violation_blocked(self):
        result = execute_python("import os\nos.listdir('.')")
        assert not result.success
        assert "import" in result.error.lower() or "violation" in result.error.lower()

    def test_timeout(self):
        code = "import time\ntime.sleep(10)"
        # time is not in allowed list, so should be blocked by import check
        result = execute_python(code, timeout=5)
        assert not result.success

    def test_pandas_available(self):
        code = "df2 = pd.DataFrame({'a': [1, 2, 3]})\nprint(len(df2))"
        result = execute_python(code)
        assert result.success
        assert "3" in result.stdout

    def test_numpy_available(self):
        code = "arr = np.array([1, 2, 3])\nprint(arr.sum())"
        result = execute_python(code)
        assert result.success
        assert "6" in result.stdout

    def test_empty_code(self):
        result = execute_python("")
        assert result.success


# --- Executor: DataFrame Capture ---


class TestDataFrameCapture:
    def test_context_df_injected(self):
        context = pd.DataFrame({"name": ["Alice", "Bob"], "value": [10, 20]})
        code = "print(len(df))"
        result = execute_python(code, context_df=context)
        assert result.success
        assert "2" in result.stdout

    def test_context_df_operations(self):
        context = pd.DataFrame({"x": [1, 2, 3, 4, 5]})
        code = "print(df['x'].mean())"
        result = execute_python(code, context_df=context)
        assert result.success
        assert "3.0" in result.stdout

    def test_result_df_captured(self):
        code = "result_df = pd.DataFrame({'col': [1, 2, 3]})"
        result = execute_python(code)
        assert result.success
        assert result.dataframe is not None
        assert len(result.dataframe) == 3
        assert "col" in result.dataframe.columns

    def test_modified_df_captured(self):
        context = pd.DataFrame({"x": [1, 2, 3]})
        code = "df = df.assign(y=df['x'] * 2)"
        result = execute_python(code, context_df=context)
        assert result.success
        assert result.dataframe is not None
        assert "y" in result.dataframe.columns

    def test_no_df_when_unchanged(self):
        context = pd.DataFrame({"x": [1]})
        code = "print('hello')"
        result = execute_python(code, context_df=context)
        assert result.success
        assert result.dataframe is None  # df wasn't reassigned


# --- Executor: Chart Capture ---


class TestChartCapture:
    def test_basic_chart(self):
        code = (
            "plt.figure()\n"
            "plt.bar(['a', 'b', 'c'], [1, 2, 3])\n"
            "plt.show()\n"
        )
        result = execute_python(code)
        assert result.success
        assert len(result.charts) == 1
        # Verify it's valid base64 PNG
        import base64
        png_bytes = base64.b64decode(result.charts[0])
        assert png_bytes[:4] == b"\x89PNG"

    def test_chart_without_show(self):
        """Charts should be captured even without plt.show()."""
        code = (
            "plt.figure()\n"
            "plt.plot([1, 2, 3], [4, 5, 6])\n"
        )
        result = execute_python(code)
        assert result.success
        assert len(result.charts) == 1

    def test_multiple_charts(self):
        code = (
            "plt.figure()\n"
            "plt.bar(['a', 'b'], [1, 2])\n"
            "plt.show()\n"
            "plt.figure()\n"
            "plt.plot([1, 2], [3, 4])\n"
            "plt.show()\n"
        )
        result = execute_python(code)
        assert result.success
        assert len(result.charts) == 2

    def test_chart_with_context_df(self):
        context = pd.DataFrame({"name": ["A", "B", "C"], "value": [10, 20, 30]})
        code = (
            "plt.figure()\n"
            "plt.bar(df['name'], df['value'])\n"
            "plt.title('Test')\n"
            "plt.show()\n"
        )
        result = execute_python(code, context_df=context)
        assert result.success
        assert len(result.charts) == 1

    def test_seaborn_available(self):
        code = (
            "data = pd.DataFrame({'x': [1,2,3,4,5], 'y': [2,4,6,8,10]})\n"
            "sns.scatterplot(data=data, x='x', y='y')\n"
            "plt.show()\n"
        )
        result = execute_python(code)
        assert result.success
        assert len(result.charts) >= 1


# --- Integration: Execute Node with Python ---


class TestExecuteNodePython:
    """Test Python action integrated into the execute node."""

    @pytest.fixture
    def test_db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, price REAL)"
        )
        conn.executemany(
            "INSERT INTO items (name, price) VALUES (?, ?)",
            [("Widget", 9.99), ("Gadget", 24.99), ("Doohickey", 4.99)],
        )
        conn.commit()
        conn.close()
        return db_path

    @pytest.fixture
    def registry_with_source(self, test_db):
        from mcpdb.sources.registry import SourceRegistry
        from mcpdb.sources.base import SourceType, SourceMetadata, TableInfo, ColumnInfo, QueryableSource

        class SQLiteSource(QueryableSource):
            def __init__(self, db_path):
                self._db_path = db_path
                self._id = "test_db"

            @property
            def source_type(self):
                return SourceType.DATABASE

            def get_metadata(self):
                return SourceMetadata(
                    source_id=self._id,
                    source_type=SourceType.DATABASE,
                    display_name="Test DB",
                    tables=[TableInfo(name="items", columns=[
                        ColumnInfo(name="id", dtype="INTEGER"),
                        ColumnInfo(name="name", dtype="TEXT"),
                        ColumnInfo(name="price", dtype="REAL"),
                    ], row_count=3)],
                    capabilities={"sql"},
                )

            def get_context_description(self):
                return "items table (id, name, price)"

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

        reg = SourceRegistry()
        reg.add_source(SQLiteSource(test_db))
        yield reg
        reg.close_all()

    @pytest.mark.asyncio
    async def test_sql_then_python_step(self, registry_with_source):
        """Execute SQL step, then Python step that uses the result."""
        from mcpdb.agent.callbacks import CallbackManager
        from mcpdb.agent.nodes.common import execute_step
        from mcpdb.agent.state import AgentState

        cb = CallbackManager()
        state: AgentState = {
            "question": "Analyze items",
            "plan": {
                "current_step_index": 0,
                "steps": [
                    {
                        "step_number": 1,
                        "action": "sql",
                        "source_id": "test_db",
                        "code": "SELECT name, price FROM items ORDER BY price DESC",
                        "status": "pending",
                        "attempts": 0,
                    },
                    {
                        "step_number": 2,
                        "action": "python",
                        "description": "Calculate stats",
                        "code": "print(f'Average price: {df[\"price\"].mean():.2f}')\nresult_df = df.describe()",
                        "status": "pending",
                        "attempts": 0,
                    },
                ],
            },
            "execution_log": [],
            "artifacts": [],
        }

        # Execute SQL step
        state = await execute_step(state, cb, registry_with_source)
        assert state["plan"]["steps"][0]["status"] == "success"
        assert state["last_result"]["dataframe"] is not None

        # Execute Python step (uses df from SQL result)
        state = await execute_step(state, cb, registry_with_source)
        assert state["plan"]["steps"][1]["status"] == "success"
        assert len(state["execution_log"]) == 2
        assert "Average price" in state["execution_log"][1]["result_preview"]

    @pytest.mark.asyncio
    async def test_python_chart_creates_artifact(self, registry_with_source):
        """Python step with chart creates a chart artifact."""
        from mcpdb.agent.callbacks import CallbackManager
        from mcpdb.agent.nodes.common import execute_step
        from mcpdb.agent.state import AgentState

        cb = CallbackManager()
        state: AgentState = {
            "question": "Visualize items",
            "plan": {
                "current_step_index": 0,
                "steps": [
                    {
                        "step_number": 1,
                        "action": "sql",
                        "source_id": "test_db",
                        "code": "SELECT name, price FROM items",
                        "status": "pending",
                        "attempts": 0,
                    },
                    {
                        "step_number": 2,
                        "action": "python",
                        "description": "Price chart",
                        "code": "plt.figure()\nplt.bar(df['name'], df['price'])\nplt.title('Item Prices')\nplt.show()",
                        "status": "pending",
                        "attempts": 0,
                    },
                ],
            },
            "execution_log": [],
            "artifacts": [],
        }

        # Execute SQL step
        state = await execute_step(state, cb, registry_with_source)
        # Execute Python chart step
        state = await execute_step(state, cb, registry_with_source)

        assert state["plan"]["steps"][1]["status"] == "success"
        chart_artifacts = [a for a in state["artifacts"] if a["type"] == "chart"]
        assert len(chart_artifacts) == 1
        assert "image_base64" in chart_artifacts[0]["data"]

    @pytest.mark.asyncio
    async def test_python_import_violation_is_error(self, registry_with_source):
        """Python step with blocked import creates an error."""
        from mcpdb.agent.callbacks import CallbackManager
        from mcpdb.agent.nodes.common import execute_step
        from mcpdb.agent.state import AgentState

        cb = CallbackManager()
        state: AgentState = {
            "question": "Test",
            "plan": {
                "current_step_index": 0,
                "steps": [{
                    "step_number": 1,
                    "action": "python",
                    "code": "import os\nos.listdir('.')",
                    "status": "pending",
                    "attempts": 0,
                }],
            },
            "execution_log": [],
            "artifacts": [],
        }

        state = await execute_step(state, cb, registry_with_source)
        assert state["current_error"] is not None
        assert "import" in state["current_error"]["error"].lower()
