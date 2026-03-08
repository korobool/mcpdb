"""Unit tests for mcpdb.web.export module.

Tests HTML report generation, notebook generation, and artifact rendering
without requiring a running web server.
"""
from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SIMPLE_TURN = {
    "question": "How many tables are in the database?",
    "response": "There are **21 tables** in the bgins database.",
    "artifacts": [],
    "executionLog": [
        {
            "step_number": 1,
            "action": "sql",
            "code": "SELECT COUNT(*) AS cnt FROM information_schema.tables WHERE table_schema = DATABASE()",
            "status": "success",
            "result_summary": "cnt: 21",
            "time_ms": 45,
        },
    ],
    "mode": "quick",
    "elapsed": 2.3,
}

CHART_TURN = {
    "question": "Plot monthly claims over time",
    "response": "Here is the monthly trend of insurance claims.\n\nThe chart shows...",
    "artifacts": [
        {
            "type": "chart",
            "title": "Monthly Claims Trend",
            "data": {"image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "format": "png"},
        },
    ],
    "executionLog": [
        {"step_number": 1, "action": "sql", "code": "SELECT DATE_FORMAT(d.damage_date, '%Y-%m') AS month, COUNT(*) AS cnt FROM ins_damages d GROUP BY month ORDER BY month", "status": "success", "result_summary": "60 rows"},
        {"step_number": 2, "action": "python", "code": "import matplotlib.pyplot as plt\nplt.plot(df['month'], df['cnt'])\nplt.title('Monthly Claims')\nplt.show()", "status": "success", "result_summary": "chart generated"},
    ],
    "mode": "simple",
    "elapsed": 12.5,
}

TABLE_TURN = {
    "question": "Top 5 car brands by claims",
    "response": "The top 5 car brands by number of claims are shown below.",
    "artifacts": [
        {
            "type": "table",
            "title": "Top Brands",
            "data": {
                "columns": ["brand", "claim_count", "avg_cost"],
                "rows": [
                    ["Mercedes", 274, 650.5],
                    ["BMW", 257, 720.3],
                    ["Audi", 234, 580.1],
                    ["VW", 220, 450.2],
                    ["Toyota", 85, 380.0],
                ],
            },
        },
    ],
    "executionLog": [
        {"step_number": 1, "action": "sql", "code": "SELECT brand, COUNT(*) as claim_count, AVG(total_cost) as avg_cost FROM ...", "status": "success", "result_summary": "5 rows"},
    ],
    "mode": "simple",
    "elapsed": 8.0,
}

MULTI_TURNS = [SIMPLE_TURN, TABLE_TURN, CHART_TURN]

ERROR_TURN = {
    "question": "Bad query",
    "response": "**Error:** Query timed out",
    "artifacts": [],
    "executionLog": [
        {"step_number": 1, "action": "sql", "code": "SELECT SLEEP(999)", "status": "error", "error": "timeout"},
    ],
    "mode": "simple",
    "elapsed": 60.0,
}


# ---------------------------------------------------------------------------
# HTML Report Tests
# ---------------------------------------------------------------------------

class TestHTMLReport:
    def test_single_turn(self):
        from mcpdb.web.export import generate_html_report
        html = generate_html_report([SIMPLE_TURN], "bgins")
        assert "<!DOCTYPE html>" in html
        assert "How many tables" in html
        assert "21 tables" in html
        assert "MCPDB" in html
        assert "bgins" in html

    def test_multiple_turns(self):
        from mcpdb.web.export import generate_html_report
        html = generate_html_report(MULTI_TURNS, "bgins")
        assert "How many tables" in html
        assert "Top 5 car brands" in html
        assert "Plot monthly claims" in html

    def test_chart_artifact_rendered(self):
        from mcpdb.web.export import generate_html_report
        html = generate_html_report([CHART_TURN])
        assert "data:image/png;base64," in html
        assert "Monthly Claims Trend" in html

    def test_table_artifact_rendered(self):
        from mcpdb.web.export import generate_html_report
        html = generate_html_report([TABLE_TURN])
        assert "<table" in html
        assert "Mercedes" in html
        assert "BMW" in html
        assert "274" in html

    def test_execution_plan_rendered(self):
        from mcpdb.web.export import generate_html_report
        html = generate_html_report([SIMPLE_TURN])
        assert "execution-plan" in html
        assert "SQL" in html

    def test_mode_and_elapsed_shown(self):
        from mcpdb.web.export import generate_html_report
        html = generate_html_report([SIMPLE_TURN])
        assert "quick" in html
        assert "2.3" in html

    def test_empty_turns(self):
        from mcpdb.web.export import generate_html_report
        html = generate_html_report([])
        assert "<!DOCTYPE html>" in html
        assert "0 turns" in html

    def test_error_turn(self):
        from mcpdb.web.export import generate_html_report
        html = generate_html_report([ERROR_TURN])
        assert "Bad query" in html
        assert "error" in html.lower()

    def test_special_characters_escaped(self):
        from mcpdb.web.export import generate_html_report
        turn = {
            "question": "What about <script>alert('xss')</script>?",
            "response": "Safe response",
            "artifacts": [], "executionLog": [], "mode": "quick", "elapsed": 1,
        }
        html = generate_html_report([turn])
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_report_is_self_contained(self):
        from mcpdb.web.export import generate_html_report
        html = generate_html_report(MULTI_TURNS)
        assert "https://" not in html
        assert "<style>" in html


# ---------------------------------------------------------------------------
# Notebook Export Tests
# ---------------------------------------------------------------------------

def _cell_source(cell: dict) -> str:
    """Get cell source as a single string (nbformat may serialize as list)."""
    src = cell["source"]
    return "".join(src) if isinstance(src, list) else src


class TestNotebookExport:
    def test_basic_notebook(self):
        from mcpdb.web.export import generate_notebook
        nb_bytes = generate_notebook(
            [SIMPLE_TURN],
            connection_string="mysql+pymysql://test@localhost/db",
            db_type="mysql",
            db_info="bgins",
        )
        nb = json.loads(nb_bytes)
        assert "cells" in nb
        assert nb["metadata"]["kernelspec"]["name"] == "python3"

    def test_setup_cell_has_connection_string(self):
        from mcpdb.web.export import generate_notebook
        nb = json.loads(generate_notebook(
            [SIMPLE_TURN],
            connection_string="mysql+pymysql://user:pass@host/db",
        ))
        setup_cell = nb["cells"][1]
        assert setup_cell["cell_type"] == "code"
        src = _cell_source(setup_cell)
        assert "mysql+pymysql://user:pass@host/db" in src
        assert "db_query" in src

    def test_sql_step_becomes_code_cell(self):
        from mcpdb.web.export import generate_notebook
        nb = json.loads(generate_notebook([SIMPLE_TURN]))
        code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
        assert len(code_cells) >= 2
        src = _cell_source(code_cells[1])
        assert "db_query" in src
        assert "information_schema" in src

    def test_python_step_becomes_code_cell(self):
        from mcpdb.web.export import generate_notebook
        nb = json.loads(generate_notebook([CHART_TURN]))
        code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
        python_cells = [c for c in code_cells if "matplotlib" in _cell_source(c)]
        assert len(python_cells) >= 1

    def test_multiple_turns(self):
        from mcpdb.web.export import generate_notebook
        nb = json.loads(generate_notebook(MULTI_TURNS))
        md_cells = [c for c in nb["cells"] if c["cell_type"] == "markdown"]
        turn_headers = [c for c in md_cells if _cell_source(c).startswith("## Turn")]
        assert len(turn_headers) == 3

    def test_response_in_markdown_cell(self):
        from mcpdb.web.export import generate_notebook
        nb = json.loads(generate_notebook([SIMPLE_TURN]))
        md_cells = [c for c in nb["cells"] if c["cell_type"] == "markdown"]
        response_cells = [c for c in md_cells if "MCPDB Response" in _cell_source(c)]
        assert len(response_cells) >= 1
        assert "21 tables" in _cell_source(response_cells[0])

    def test_security_notice(self):
        from mcpdb.web.export import generate_notebook
        nb = json.loads(generate_notebook([SIMPLE_TURN]))
        title_cell = nb["cells"][0]
        assert "Security Notice" in _cell_source(title_cell)

    def test_pip_install_mysql(self):
        from mcpdb.web.export import generate_notebook
        nb = json.loads(generate_notebook([SIMPLE_TURN], db_type="mysql"))
        setup = _cell_source(nb["cells"][1])
        assert "pymysql" in setup

    def test_pip_install_postgresql(self):
        from mcpdb.web.export import generate_notebook
        nb = json.loads(generate_notebook([SIMPLE_TURN], db_type="postgresql"))
        setup = _cell_source(nb["cells"][1])
        assert "psycopg2" in setup

    def test_triple_quote_sql_escaped(self):
        from mcpdb.web.export import generate_notebook
        turn = {
            "question": "test", "response": "ok", "artifacts": [],
            "executionLog": [{
                "step_number": 1, "action": "sql",
                "code": 'SELECT """triple""" FROM t',
                "status": "success", "result_summary": "1 row",
            }],
            "mode": "quick", "elapsed": 1,
        }
        nb = json.loads(generate_notebook([turn]))
        code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
        for c in code_cells:
            src = _cell_source(c)
            if "db_query" in src:
                assert '"""triple"""' not in src

    def test_failed_steps_skipped(self):
        from mcpdb.web.export import generate_notebook
        nb = json.loads(generate_notebook([ERROR_TURN]))
        code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
        assert len(code_cells) == 1  # just setup


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

class TestRendering:
    def test_markdown_to_html_basic(self):
        from mcpdb.web.export import _markdown_to_html
        html = _markdown_to_html("**bold** and *italic*")
        assert "<strong>bold</strong>" in html
        assert "<em>italic</em>" in html

    def test_markdown_to_html_code_block(self):
        from mcpdb.web.export import _markdown_to_html
        html = _markdown_to_html("```sql\nSELECT 1\n```")
        assert "SELECT" in html
        assert "<pre" in html or "<code" in html

    def test_render_chart_artifact(self):
        from mcpdb.web.export import _render_artifacts_html
        html = _render_artifacts_html([{
            "type": "chart", "title": "Test Chart",
            "data": {"image_base64": "abc123", "format": "png"},
        }])
        assert "data:image/png;base64,abc123" in html
        assert "Test Chart" in html

    def test_render_table_artifact(self):
        from mcpdb.web.export import _render_artifacts_html
        html = _render_artifacts_html([{
            "type": "table", "title": "Results",
            "data": {"columns": ["Name", "Value"], "rows": [["Alice", 100], ["Bob", 200]]},
        }])
        assert "<table" in html
        assert "Alice" in html
        assert "200" in html

    def test_render_empty_artifacts(self):
        from mcpdb.web.export import _render_artifacts_html
        assert _render_artifacts_html([]) == ""

    def test_render_plan_html(self):
        from mcpdb.web.export import _render_plan_html
        html = _render_plan_html([
            {"step_number": 1, "action": "sql", "status": "success", "result_summary": "5 rows"},
            {"step_number": 2, "action": "python", "status": "error", "error": "NameError"},
        ])
        assert "step-done" in html
        assert "step-failed" in html
        assert "SQL" in html
        assert "PYTHON" in html

    def test_render_plan_empty(self):
        from mcpdb.web.export import _render_plan_html
        assert _render_plan_html([]) == ""
