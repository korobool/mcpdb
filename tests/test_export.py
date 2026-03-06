"""Tests for v3.2.x — Export (HTML, PDF, Jupyter, MCP tool, UI dialog)."""

from __future__ import annotations

import json
import os

import pytest

from mcpdb.export.html_export import (
    ExportArtifact,
    ExportMessage,
    ExportPayload,
    render_html,
)
from mcpdb.export.notebook_export import (
    render_notebook,
    render_notebook_json,
    export_notebook,
)


# ---------------------------------------------------------------------------
# ExportPayload tests
# ---------------------------------------------------------------------------

class TestExportPayload:
    def test_defaults(self):
        p = ExportPayload()
        assert p.title == "MCPDB Analysis"
        assert p.messages == []
        assert p.artifacts == []
        assert p.metadata == {}

    def test_with_messages(self):
        p = ExportPayload(
            messages=[
                ExportMessage(role="user", content="Hello"),
                ExportMessage(role="assistant", content="Hi there"),
            ]
        )
        assert len(p.messages) == 2
        assert p.messages[0].role == "user"

    def test_with_artifacts(self):
        p = ExportPayload(
            artifacts=[
                ExportArtifact(artifact_type="table", title="Results"),
                ExportArtifact(artifact_type="chart", title="Chart"),
            ]
        )
        assert len(p.artifacts) == 2

    def test_with_metadata(self):
        p = ExportPayload(metadata={"source": "test.db", "date": "2024-01-01"})
        assert p.metadata["source"] == "test.db"


# ---------------------------------------------------------------------------
# HTML rendering tests
# ---------------------------------------------------------------------------

class TestHTMLExport:
    def test_basic_render(self):
        html = render_html(ExportPayload())
        assert "<!DOCTYPE html>" in html
        assert "MCPDB Analysis" in html
        assert "</html>" in html

    def test_custom_title(self):
        html = render_html(ExportPayload(title="My Report"))
        assert "My Report" in html
        assert "<title>My Report</title>" in html

    def test_messages_rendered(self):
        p = ExportPayload(messages=[
            ExportMessage(role="user", content="What tables exist?"),
            ExportMessage(role="assistant", content="There are 3 tables."),
        ])
        html = render_html(p)
        assert "What tables exist?" in html
        assert "There are 3 tables." in html
        assert "msg-user" in html
        assert "msg-assistant" in html

    def test_metadata_rendered(self):
        p = ExportPayload(metadata={"source": "postgres", "date": "2024-01-01"})
        html = render_html(p)
        assert "postgres" in html
        assert "2024-01-01" in html

    def test_table_artifact(self):
        p = ExportPayload(artifacts=[
            ExportArtifact(
                artifact_type="table",
                title="Results",
                data={
                    "columns": ["name", "age"],
                    "rows": [
                        {"name": "Alice", "age": "30"},
                        {"name": "Bob", "age": "25"},
                    ],
                },
            )
        ])
        html = render_html(p)
        assert "<table>" in html
        assert "Alice" in html
        assert "Bob" in html
        assert "name" in html
        assert "age" in html

    def test_table_with_list_rows(self):
        p = ExportPayload(artifacts=[
            ExportArtifact(
                artifact_type="table",
                title="Data",
                data={
                    "columns": ["x", "y"],
                    "rows": [["1", "2"], ["3", "4"]],
                },
            )
        ])
        html = render_html(p)
        assert "<table>" in html
        assert "1" in html

    def test_chart_artifact(self):
        p = ExportPayload(artifacts=[
            ExportArtifact(
                artifact_type="chart",
                title="My Chart",
                data="iVBORw0KGgo=",  # fake base64
            )
        ])
        html = render_html(p)
        assert "data:image/png;base64,iVBORw0KGgo=" in html
        assert "My Chart" in html

    def test_code_artifact(self):
        p = ExportPayload(artifacts=[
            ExportArtifact(
                artifact_type="code",
                title="Query",
                data="SELECT * FROM users",
            )
        ])
        html = render_html(p)
        assert "<pre>" in html
        assert "SELECT * FROM users" in html

    def test_html_escaping(self):
        p = ExportPayload(
            title="<script>alert('xss')</script>",
            messages=[
                ExportMessage(role="user", content="<b>bold</b>"),
            ],
        )
        html = render_html(p)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "&lt;b&gt;" in html

    def test_footer_present(self):
        html = render_html(ExportPayload())
        assert "Generated by MCPDB" in html

    def test_css_present(self):
        html = render_html(ExportPayload())
        assert "<style>" in html
        assert "font-family" in html

    def test_empty_messages_and_artifacts(self):
        html = render_html(ExportPayload(messages=[], artifacts=[]))
        assert "<!DOCTYPE html>" in html


# ---------------------------------------------------------------------------
# Notebook rendering tests
# ---------------------------------------------------------------------------

class TestNotebookExport:
    def test_basic_notebook(self):
        nb = render_notebook(ExportPayload())
        assert nb["nbformat"] == 4
        assert "cells" in nb
        assert len(nb["cells"]) >= 1  # at least the title cell

    def test_title_cell(self):
        nb = render_notebook(ExportPayload(title="Test Report"))
        title_cell = nb["cells"][0]
        assert title_cell["cell_type"] == "markdown"
        assert any("Test Report" in line for line in title_cell["source"])

    def test_messages_as_cells(self):
        p = ExportPayload(messages=[
            ExportMessage(role="user", content="Hello"),
            ExportMessage(role="assistant", content="World"),
        ])
        nb = render_notebook(p)
        # Title + metadata + 2 message cells = at least 3
        assert len(nb["cells"]) >= 3
        sources = ["\n".join(c["source"]) for c in nb["cells"]]
        all_text = "\n".join(sources)
        assert "Hello" in all_text
        assert "World" in all_text

    def test_code_artifact_as_code_cell(self):
        p = ExportPayload(
            messages=[ExportMessage(role="user", content="Test")],
            artifacts=[
                ExportArtifact(
                    artifact_type="code",
                    title="Query",
                    data="print('hello')",
                    step_number=0,
                )
            ],
        )
        nb = render_notebook(p)
        code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
        assert len(code_cells) >= 1

    def test_table_artifact_as_pandas_code(self):
        p = ExportPayload(
            messages=[ExportMessage(role="user", content="Show data")],
            artifacts=[
                ExportArtifact(
                    artifact_type="table",
                    title="Results",
                    data={
                        "columns": ["a", "b"],
                        "rows": [{"a": 1, "b": 2}],
                    },
                    step_number=0,
                )
            ],
        )
        nb = render_notebook(p)
        code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
        assert len(code_cells) >= 1
        code_text = "\n".join(code_cells[0]["source"])
        assert "pandas" in code_text

    def test_notebook_json_valid(self):
        nb_json = render_notebook_json(ExportPayload(title="JSON Test"))
        parsed = json.loads(nb_json)
        assert parsed["nbformat"] == 4
        assert "cells" in parsed

    def test_export_to_file(self, tmp_path):
        out = str(tmp_path / "test.ipynb")
        result = export_notebook(ExportPayload(title="File Test"), out)
        assert result == out
        assert os.path.exists(out)
        with open(out) as f:
            nb = json.load(f)
        assert nb["nbformat"] == 4

    def test_metadata_cell(self):
        p = ExportPayload(metadata={"source": "test.db"})
        nb = render_notebook(p)
        # Should have title + metadata cells
        assert len(nb["cells"]) >= 2

    def test_kernelspec(self):
        nb = render_notebook(ExportPayload())
        assert nb["metadata"]["kernelspec"]["language"] == "python"

    def test_chart_artifact_as_markdown(self):
        p = ExportPayload(
            messages=[ExportMessage(role="user", content="Chart")],
            artifacts=[
                ExportArtifact(
                    artifact_type="chart",
                    title="Plot",
                    data="base64data",
                    step_number=0,
                )
            ],
        )
        nb = render_notebook(p)
        md_cells = [c for c in nb["cells"] if c["cell_type"] == "markdown"]
        all_md = "\n".join("\n".join(c["source"]) for c in md_cells)
        assert "base64data" in all_md


# ---------------------------------------------------------------------------
# PDF export tests (import only — weasyprint may not be installed)
# ---------------------------------------------------------------------------

class TestPDFExport:
    def test_import_pdf_module(self):
        from mcpdb.export.pdf_export import render_pdf, export_pdf
        assert callable(render_pdf)
        assert callable(export_pdf)


# ---------------------------------------------------------------------------
# MCP export tool tests
# ---------------------------------------------------------------------------

class TestExportTool:
    def test_get_tools(self):
        from mcpdb.mcp.tools.export import get_export_tools
        tools = get_export_tools()
        assert len(tools) == 1
        assert tools[0].name == "export_conversation"

    def test_handle_html_export(self, tmp_path):
        from mcpdb.mcp.tools.export import handle_export_tool
        out_path = str(tmp_path / "test.html")
        result = handle_export_tool("export_conversation", {
            "format": "html",
            "title": "Test",
            "output_path": out_path,
            "messages": [{"role": "user", "content": "Hello"}],
        })
        assert len(result) == 1
        assert out_path in result[0].text
        assert os.path.exists(out_path)
        with open(out_path) as f:
            content = f.read()
        assert "Hello" in content

    def test_handle_notebook_export(self, tmp_path):
        from mcpdb.mcp.tools.export import handle_export_tool
        out_path = str(tmp_path / "test.ipynb")
        result = handle_export_tool("export_conversation", {
            "format": "notebook",
            "title": "NB Test",
            "output_path": out_path,
            "messages": [
                {"role": "user", "content": "Q"},
                {"role": "assistant", "content": "A"},
            ],
        })
        assert len(result) == 1
        assert out_path in result[0].text
        with open(out_path) as f:
            nb = json.load(f)
        assert nb["nbformat"] == 4

    def test_handle_auto_path(self, tmp_path, monkeypatch):
        import tempfile
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        from mcpdb.mcp.tools.export import handle_export_tool
        result = handle_export_tool("export_conversation", {
            "format": "html",
            "title": "Auto",
        })
        assert "exported to" in result[0].text.lower()

    def test_handle_unknown_format(self):
        from mcpdb.mcp.tools.export import handle_export_tool
        result = handle_export_tool("export_conversation", {
            "format": "docx",
        })
        assert "unknown format" in result[0].text.lower()

    def test_handle_unknown_tool(self):
        from mcpdb.mcp.tools.export import handle_export_tool
        result = handle_export_tool("unknown_tool", {})
        assert "unknown" in result[0].text.lower()

    def test_handle_with_artifacts(self, tmp_path):
        from mcpdb.mcp.tools.export import handle_export_tool
        out_path = str(tmp_path / "art.html")
        result = handle_export_tool("export_conversation", {
            "format": "html",
            "output_path": out_path,
            "artifacts": [
                {"type": "table", "title": "Results", "data": {
                    "columns": ["x"], "rows": [{"x": 1}],
                }},
            ],
        })
        assert os.path.exists(out_path)
        with open(out_path) as f:
            content = f.read()
        assert "Results" in content


# ---------------------------------------------------------------------------
