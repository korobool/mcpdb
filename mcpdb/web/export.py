"""Export conversation history to HTML, PDF, and Jupyter notebook.

Converts the turn-based conversation data sent from the frontend into
standalone export formats.  Charts are already base64-encoded PNGs from
the agent pipeline, so no matplotlib objects are needed.

Pipeline:
    turns (JSON) → HTML report (Jinja2 + markdown)
    turns (JSON) → HTML → PDF (WeasyPrint)
    turns (JSON) → .ipynb (nbformat) with re-runnable code cells
"""
from __future__ import annotations

import base64
import json as _json
import logging
import re
import urllib.error
import urllib.request
from datetime import datetime
from html import escape as html_escape
from typing import Any

logger = logging.getLogger("mcpdb.web.export")


# ---------------------------------------------------------------------------
# Markdown → HTML
# ---------------------------------------------------------------------------

MERMAID_PATTERN = re.compile(r"```mermaid\s*([\s\S]*?)```")


def _mermaid_to_base64_uri(mermaid_code: str, timeout: float = 10.0) -> str | None:
    """Render mermaid code to a PNG via kroki.io (fallback: mermaid.ink)."""
    try:
        encoded = base64.urlsafe_b64encode(mermaid_code.encode()).decode()
        url = f"https://kroki.io/mermaid/png/{encoded}"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            b64 = base64.b64encode(resp.read()).decode()
        return f"data:image/png;base64,{b64}"
    except Exception:
        pass
    try:
        payload = _json.dumps({"code": mermaid_code, "mermaid": {"theme": "default"}})
        encoded = base64.urlsafe_b64encode(payload.encode()).decode()
        url = f"https://mermaid.ink/img/{encoded}"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            b64 = base64.b64encode(resp.read()).decode()
        return f"data:image/png;base64,{b64}"
    except Exception as e:
        logger.warning("Mermaid render failed: %s", e)
        return None


def _markdown_to_html(text: str) -> str:
    """Convert markdown to HTML, rendering mermaid blocks as images."""
    try:
        import markdown as md_lib
    except ImportError:
        # Fallback: just wrap in <p> tags
        return f"<p>{html_escape(text)}</p>"

    def _replace_mermaid(m):
        code = m.group(1).strip()
        uri = _mermaid_to_base64_uri(code)
        if uri:
            return f'<div class="mermaid-diagram"><img src="{uri}" alt="Diagram"></div>'
        return f'<div class="mermaid-fallback"><pre><code>{html_escape(code)}</code></pre></div>'

    text = MERMAID_PATTERN.sub(_replace_mermaid, text)
    extensions = ["fenced_code", "tables", "codehilite", "sane_lists"]
    ext_cfg = {"codehilite": {"css_class": "highlight", "linenums": False}}
    converter = md_lib.Markdown(extensions=extensions, extension_configs=ext_cfg)
    html = converter.convert(text)
    converter.reset()
    return html


# ---------------------------------------------------------------------------
# Turn rendering helpers
# ---------------------------------------------------------------------------

def _coerce_artifact_data(data: Any) -> dict:
    """Coerce artifact data to a dict — handles string-encoded data from WebSocket."""
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        # Try JSON first
        try:
            parsed = _json.loads(data)
            if isinstance(parsed, dict):
                return parsed
        except (_json.JSONDecodeError, ValueError):
            pass
        # Try Python literal (handles datetime.date repr etc.)
        try:
            import ast
            parsed = ast.literal_eval(data)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, SyntaxError):
            pass
    return {}


def _render_artifacts_html(artifacts: list[dict]) -> str:
    """Render artifact list to HTML."""
    parts: list[str] = []
    for art in artifacts:
        try:
            atype = art.get("type")
            data = _coerce_artifact_data(art.get("data", {}))

            if atype == "chart":
                b64 = data.get("image_base64", "")
                fmt = data.get("format", "png")
                title = html_escape(art.get("title", ""))
                if b64:
                    title_html = f'<p class="chart-title">{title}</p>' if title else ""
                    parts.append(
                        f'{title_html}<div class="chart-container">'
                        f'<img src="data:image/{fmt};base64,{b64}" alt="{title or "Chart"}">'
                        f"</div>"
                    )

            elif atype == "table":
                cols = data.get("columns", [])
                rows = data.get("rows", [])
                title = html_escape(art.get("title", ""))
                if cols:
                    title_html = f'<p class="table-title">{title}</p>' if title else ""
                    # Build HTML table
                    header = "".join(f"<th>{html_escape(str(c))}</th>" for c in cols)
                    body_rows = []
                    for row in rows[:200]:
                        cells = "".join(f"<td>{html_escape(str(v))}</td>" for v in row)
                        body_rows.append(f"<tr>{cells}</tr>")
                    parts.append(
                        f'{title_html}<table class="data-table">'
                        f"<thead><tr>{header}</tr></thead>"
                        f"<tbody>{''.join(body_rows)}</tbody></table>"
                    )
        except Exception as e:
            logger.warning("Failed to render artifact: %s", e)
            continue

    return "\n".join(parts)


def _render_plan_html(execution_log: list[dict]) -> str:
    """Render execution log as a plan summary."""
    if not execution_log:
        return ""
    parts = ['<div class="execution-plan">', "<h4>Execution Plan</h4>", "<ol>"]
    for entry in execution_log:
        status = entry.get("status", "pending")
        css = {"success": "step-done", "error": "step-failed"}.get(status, "step-pending")
        action = html_escape(entry.get("action", "").upper())
        step_num = entry.get("step_number", "?")
        summary = html_escape(str(entry.get("result_summary", entry.get("error", "")))[:150])
        parts.append(f'<li class="{css}">[{action}] Step {step_num}: {summary}</li>')
    parts.append("</ol></div>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

def generate_html_report(turns: list[dict], db_info: str = "") -> str:
    """Generate a self-contained HTML report from conversation turns.

    Each turn: {question, response, artifacts, executionLog, mode, elapsed}
    """
    export_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    turns_html = []
    for i, turn in enumerate(turns):
        turns_html.append({
            "number": i + 1,
            "user_message": html_escape(turn.get("question", "")),
            "ai_message_html": _markdown_to_html(turn.get("response", "")),
            "artifacts_html": _render_artifacts_html(turn.get("artifacts", [])),
            "plan_html": _render_plan_html(turn.get("executionLog", [])),
            "mode": turn.get("mode", ""),
            "elapsed": turn.get("elapsed", 0),
        })

    from jinja2 import Template
    template = Template(HTML_REPORT_TEMPLATE)
    return template.render(
        title="MCPDB — Analysis Report",
        db_info=html_escape(db_info),
        export_date=export_date,
        turns=turns_html,
        total_turns=len(turns_html),
    )


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------

def generate_pdf(turns: list[dict], db_info: str = "") -> bytes:
    """Generate a PDF from conversation turns. Requires weasyprint."""
    try:
        from weasyprint import HTML
    except ImportError:
        raise ImportError(
            "WeasyPrint is required for PDF export. Install with: pip install weasyprint"
        )
    html_content = generate_html_report(turns, db_info)
    return HTML(string=html_content).write_pdf()


# ---------------------------------------------------------------------------
# Jupyter notebook export
# ---------------------------------------------------------------------------

DB_DRIVER_PACKAGES = {
    "mysql": ["pymysql"],
    "postgresql": ["psycopg2-binary"],
    "mssql": ["pyodbc"],
    "sqlite": [],
    "csv": [],
}


def generate_notebook(
    turns: list[dict],
    connection_string: str = "",
    db_type: str = "mysql",
    db_info: str = "",
) -> bytes:
    """Generate a self-contained Jupyter notebook from conversation turns.

    The notebook includes setup cells with hardcoded connection strings,
    code cells for each SQL/Python step, and pre-populated outputs.
    """
    try:
        import nbformat
        from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook
    except ImportError:
        raise ImportError("nbformat is required. Install with: pip install nbformat")

    nb = new_notebook()
    nb.metadata = {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.10.0"},
    }

    export_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Title cell
    nb.cells.append(new_markdown_cell(source="\n".join([
        "# MCPDB — Notebook Export\n",
        f"**Database:** {db_info or db_type}  ",
        f"**Exported:** {export_date}  ",
        f"**Turns:** {len(turns)}\n",
        "> **Security Notice:** This notebook contains database connection credentials.  ",
        "> Remove the `CONNECTION_STRING` value before sharing.\n",
        "---\n",
        "Run the **setup cell** first, then execute cells in order.",
    ])))

    # Setup cell
    driver_pkgs = DB_DRIVER_PACKAGES.get(db_type, [])
    base_pkgs = ["sqlalchemy", "pandas", "matplotlib", "seaborn", "numpy"]
    pip_line = "!pip install -q " + " ".join(base_pkgs + driver_pkgs)

    setup_code = f"""{pip_line}

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sqlalchemy import create_engine, text

%matplotlib inline
pd.set_option("display.max_columns", 50)
pd.set_option("display.width", 200)

# --- Database connection ---
CONNECTION_STRING = "{connection_string}"
engine = create_engine(CONNECTION_STRING)


def db_query(sql: str, max_rows: int = 100) -> pd.DataFrame:
    \"\"\"Execute SQL and return a DataFrame.\"\"\"
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        rows = result.fetchmany(max_rows + 1)
        columns = list(result.keys())
        truncated = len(rows) > max_rows
        if truncated:
            rows = rows[:max_rows]
        df = pd.DataFrame(rows, columns=columns)
        if truncated:
            print(f"Note: Results truncated to {{max_rows}} rows")
        return df


# Verify connection
with engine.connect() as _conn:
    print("Connected to database successfully.")
"""
    nb.cells.append(new_code_cell(source=setup_code))

    # Turn cells
    for i, turn in enumerate(turns):
        question = turn.get("question", "")
        response = turn.get("response", "")
        exec_log = turn.get("executionLog", [])
        mode = turn.get("mode", "")

        # Turn header
        header = f"## Turn {i + 1}: {question}\n"
        if mode:
            header += f"> **Mode:** {mode}\n"
        nb.cells.append(new_markdown_cell(source=header))

        # Code cells for each step
        for entry in exec_log:
            if entry.get("status") != "success":
                continue
            action = entry.get("action", "")
            code = entry.get("code", "")
            step_num = entry.get("step_number", "?")
            summary = entry.get("result_summary", "")

            if not code:
                continue

            # Step description
            nb.cells.append(new_markdown_cell(
                source=f"### Step {step_num} `[{action.upper()}]`"
            ))

            # Build code cell
            if action == "sql":
                sql_code = code.strip()
                if '"""' in sql_code:
                    sql_code = sql_code.replace('"""', "'''")
                cell_code = f'df = db_query("""\n{sql_code}\n""")\ndf'
            else:
                cell_code = code

            code_cell = new_code_cell(source=cell_code)
            code_cell.outputs = []

            # Pre-populate output with result summary
            if summary:
                code_cell.outputs.append(nbformat.v4.new_output(
                    output_type="stream", name="stdout", text=summary[:500],
                ))

            nb.cells.append(code_cell)

        # AI response
        if response:
            nb.cells.append(new_markdown_cell(
                source=f"---\n\n**MCPDB Response:**\n\n{response}"
            ))

    # Footer
    nb.cells.append(new_markdown_cell(
        source=f"---\n\n*Generated by MCPDB on {export_date}*"
    ))

    return nbformat.writes(nb, version=4).encode("utf-8")


# ---------------------------------------------------------------------------
# Jupyter server management
# ---------------------------------------------------------------------------

_jupyter_proc = None


def start_jupyter_and_open(notebook_bytes: bytes, filename: str = "") -> str:
    """Save notebook to temp dir, start Jupyter if needed, return URL.

    Returns the URL for the browser to open.
    """
    import os
    import signal
    import socket
    import subprocess
    import sys
    import tempfile

    global _jupyter_proc

    # Save notebook
    nb_dir = Path.home() / ".mcpdb" / "jupyter"
    nb_dir.mkdir(parents=True, exist_ok=True)

    if not filename:
        filename = f"mcpdb_{datetime.now().strftime('%Y%m%d_%H%M%S')}.ipynb"
    nb_path = nb_dir / filename
    nb_path.write_bytes(notebook_bytes)

    # Sign notebook for trust
    try:
        import nbformat
        from nbformat.sign import NotebookNotary
        nb = nbformat.read(str(nb_path), as_version=4)
        NotebookNotary().sign(nb)
        nbformat.write(nb, str(nb_path))
    except Exception as e:
        logger.warning("Failed to sign notebook: %s", e)

    # Check if Jupyter is already running on port 8888
    port = 8888
    jupyter_running = False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            jupyter_running = True
    except OSError:
        pass

    # Also check our tracked process
    if _jupyter_proc is not None:
        if _jupyter_proc.poll() is not None:
            _jupyter_proc = None  # Process died

    if not jupyter_running and _jupyter_proc is None:
        # Start Jupyter
        _jupyter_proc = subprocess.Popen(
            [
                sys.executable, "-m", "jupyter", "notebook",
                "--no-browser",
                f"--port={port}",
                f"--notebook-dir={nb_dir}",
                "--NotebookApp.token=",
                "--NotebookApp.password=",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for startup
        import time
        for _ in range(30):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(0.5)

    return f"http://localhost:{port}/notebooks/{filename}"


from pathlib import Path


# ---------------------------------------------------------------------------
# HTML report template
# ---------------------------------------------------------------------------

HTML_REPORT_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ title }}</title>
<style>
*, *::before, *::after { box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    font-size: 15px; line-height: 1.65; color: #1e293b;
    background: #f1f5f9; margin: 0; padding: 0;
}
.report-header {
    background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%);
    color: white; padding: 32px 0;
    position: sticky; top: 0; z-index: 100;
    box-shadow: 0 4px 24px rgba(37, 99, 235, .3);
}
.report-header .inner { max-width: 900px; margin: 0 auto; padding: 0 24px; }
.report-header h1 { margin: 0 0 6px 0; font-size: 26px; font-weight: 700; }
.report-header .meta { font-size: 13px; opacity: .85; display: flex; gap: 16px; flex-wrap: wrap; }
.container { max-width: 900px; margin: 0 auto; padding: 24px 24px 48px; }
.turn {
    background: white; border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,.08); margin-bottom: 20px; overflow: hidden;
    transition: box-shadow .2s;
}
.turn:hover { box-shadow: 0 4px 12px rgba(0,0,0,.1); }
.user-message {
    background: #eff6ff; border-left: 4px solid #3b82f6; padding: 14px 20px;
}
.user-message .label {
    font-size: 11px; font-weight: 700; color: #3b82f6;
    text-transform: uppercase; letter-spacing: .8px; margin-bottom: 4px;
}
.user-message p { margin: 0; }
.ai-response { padding: 16px 20px; }
.ai-response .label {
    font-size: 11px; font-weight: 700; color: #7c3aed;
    text-transform: uppercase; letter-spacing: .8px; margin-bottom: 8px;
}
.ai-response h1, .ai-response h2, .ai-response h3, .ai-response h4 {
    margin-top: 16px; margin-bottom: 6px; color: #0f172a;
}
.ai-response h1 { font-size: 22px; } .ai-response h2 { font-size: 19px; }
.ai-response h3 { font-size: 16px; }
.ai-response ul, .ai-response ol { padding-left: 24px; }
.ai-response p { margin: 8px 0; }
.ai-response blockquote {
    border-left: 3px solid #cbd5e1; margin: 12px 0; padding: 4px 16px;
    color: #475569; background: #f8fafc; border-radius: 0 6px 6px 0;
}
.ai-response code {
    background: #f1f5f9; padding: 2px 6px; border-radius: 4px;
    font-size: 13px; font-family: 'JetBrains Mono', 'Fira Code', monospace; color: #e11d48;
}
.ai-response pre {
    background: #0f172a; color: #e2e8f0; padding: 16px 20px; border-radius: 8px;
    font-size: 13px; line-height: 1.5; overflow-x: auto; white-space: pre-wrap; word-wrap: break-word;
}
.ai-response pre code { background: none; padding: 0; color: inherit; }
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; margin: 14px 0; }
.data-table thead th {
    background: #2563eb; color: white; padding: 10px 12px; text-align: left; font-weight: 600;
}
.data-table tbody td { padding: 8px 12px; border-bottom: 1px solid #e2e8f0; }
.data-table tbody tr:nth-child(even) { background: #f8fafc; }
.data-table tbody tr:hover { background: #eff6ff; }
.table-title { font-weight: 600; font-size: 14px; color: #374151; margin-bottom: 4px; }
.chart-container { text-align: center; margin: 16px 0; padding: 12px; }
.chart-container img { max-width: 100%; height: auto; border-radius: 6px; }
.chart-title { font-weight: 600; font-size: 14px; color: #374151; text-align: center; margin-bottom: 8px; }
.mermaid-diagram { text-align: center; margin: 16px 0; padding: 16px; }
.mermaid-diagram img { max-width: 100%; height: auto; }
.mermaid-fallback { background: #fffbeb; border: 1px solid #fcd34d; border-radius: 8px; padding: 14px; margin: 12px 0; }
.execution-plan {
    background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px;
    padding: 14px 20px; margin: 10px 20px 14px; font-size: 14px;
}
.execution-plan h4 { margin: 0 0 8px 0; color: #166534; font-size: 15px; }
.execution-plan ol { padding-left: 22px; }
.execution-plan li { margin-bottom: 4px; }
.step-done { color: #166534; } .step-failed { color: #991b1b; text-decoration: line-through; }
.step-pending { color: #6b7280; }
.msg-meta { font-size: 12px; color: #94a3b8; margin-top: 12px; padding-top: 8px; border-top: 1px solid #e2e8f0; }
.report-footer {
    max-width: 900px; margin: 0 auto 48px; padding: 16px 24px;
    text-align: center; font-size: 13px; color: #94a3b8;
}
@media (max-width: 640px) {
    .report-header h1 { font-size: 20px; }
    .container { padding: 12px; }
    .turn { border-radius: 8px; }
    .user-message, .ai-response { padding: 12px 14px; }
}
@media print {
    body { background: white; }
    .report-header { position: static; box-shadow: none; }
    .turn { box-shadow: none; break-inside: avoid; }
}
</style>
</head>
<body>

<div class="report-header">
    <div class="inner">
        <h1>MCPDB — Analysis Report</h1>
        <div class="meta">
            {% if db_info %}<span>{{ db_info }}</span>{% endif %}
            <span>{{ export_date }}</span>
            <span>{{ total_turns }} turn{{ 's' if total_turns != 1 else '' }}</span>
        </div>
    </div>
</div>

<div class="container">
{% for turn in turns %}
<div class="turn">
    <div class="user-message">
        <div class="label">You</div>
        <p>{{ turn.user_message }}</p>
    </div>

    {% if turn.plan_html %}
    {{ turn.plan_html }}
    {% endif %}

    <div class="ai-response">
        <div class="label">MCPDB</div>
        {{ turn.ai_message_html }}
        {{ turn.artifacts_html }}
        {% if turn.mode or turn.elapsed %}
        <div class="msg-meta">
            {% if turn.mode %}Mode: {{ turn.mode }}{% endif %}
            {% if turn.mode and turn.elapsed %} &middot; {% endif %}
            {% if turn.elapsed %}Time: {{ "%.1f"|format(turn.elapsed) }}s{% endif %}
        </div>
        {% endif %}
    </div>
</div>
{% endfor %}
</div>

<div class="report-footer">
    Generated by MCPDB &middot; {{ export_date }}
</div>

</body>
</html>
"""
