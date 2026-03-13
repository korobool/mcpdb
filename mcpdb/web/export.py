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

_MERMAID_UNSAFE = re.compile(r"[^A-Za-z0-9_]")
_MULTI_UNDERSCORE = re.compile(r"_+")


def _sanitize_mermaid_id(name: str) -> str:
    """Sanitize identifier for mermaid erDiagram (alphanumeric + underscore)."""
    name = name.replace(" ", "_").replace("-", "_")
    name = _MERMAID_UNSAFE.sub("", name)
    name = _MULTI_UNDERSCORE.sub("_", name)
    return name or "unnamed"


def _sanitize_mermaid_erd(code: str) -> str:
    """Sanitize an erDiagram block so identifiers are mermaid-safe."""
    if not re.search(r"^\s*erDiagram\b", code, re.M):
        return code
    lines: list[str] = []
    for line in code.split("\n"):
        # Entity definition: "    EntityName {"
        m = re.match(r"^(\s*)(\S+)(\s*\{)\s*$", line)
        if m:
            lines.append(m.group(1) + _sanitize_mermaid_id(m.group(2)) + m.group(3))
            continue
        # Closing brace
        if re.match(r"^\s*\}\s*$", line):
            lines.append(line)
            continue
        # Attribute: "        type name PK/FK"
        m = re.match(r"^(\s+)(\S+)\s+(.+?)(\s+(?:PK|FK))?\s*$", line)
        if m and "|" not in line and "{" not in line:
            indent = m.group(1)
            dtype = re.sub(r"[\s(),'\"]+", "_", m.group(2)).strip("_") or "unknown"
            raw_name = re.sub(r'\s*"[^"]*"\s*$', "", m.group(3)).strip()
            safe_name = _sanitize_mermaid_id(raw_name)
            marker = m.group(4) or ""
            lines.append(f"{indent}{dtype} {safe_name}{marker}")
            continue
        # Relationship with quoted label
        m = re.match(
            r'^(\s*)(\S+)(\s*(?:[\|\.o\{}\<\>])+(?:--?|\.\.)(?:[\|\.o\{}\<\>])+\s*)(\S+)(\s*:\s*)"([^"]*)"(.*)$',
            line,
        )
        if m:
            lines.append(
                m.group(1) + _sanitize_mermaid_id(m.group(2)) + m.group(3)
                + _sanitize_mermaid_id(m.group(4)) + m.group(5)
                + '"' + _sanitize_mermaid_id(m.group(6)) + '"' + m.group(7)
            )
            continue
        lines.append(line)
    return "\n".join(lines)


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


_TABLE_LINE = re.compile(r"^\|.+\|$")


def _fix_markdown_tables(text: str) -> str:
    """Ensure blank lines before markdown tables (required by Python-Markdown).

    LLM responses often omit the blank line before a table, e.g.:
        Here is the data:
        | col1 | col2 |
        | --- | --- |
    We insert a blank line before the first pipe-row so the parser picks it up.
    """
    lines = text.split("\n")
    fixed: list[str] = []
    for i, line in enumerate(lines):
        if _TABLE_LINE.match(line.strip()) and i > 0 and fixed and fixed[-1].strip() != "":
            # Previous line is non-empty and current is a table row — insert blank line
            if not _TABLE_LINE.match(fixed[-1].strip()):
                fixed.append("")
        fixed.append(line)
    return "\n".join(fixed)


def _markdown_to_html(text: str) -> str:
    """Convert markdown to HTML, rendering mermaid blocks as images."""
    try:
        import markdown as md_lib
    except ImportError:
        # Fallback: just wrap in <p> tags
        return f"<p>{html_escape(text)}</p>"

    def _replace_mermaid(m):
        code = _sanitize_mermaid_erd(m.group(1).strip())
        uri = _mermaid_to_base64_uri(code)
        if uri:
            return f'<div class="mermaid-diagram"><img src="{uri}" alt="Diagram"></div>'
        return f'<div class="mermaid-fallback"><pre><code>{html_escape(code)}</code></pre></div>'

    text = MERMAID_PATTERN.sub(_replace_mermaid, text)
    text = _fix_markdown_tables(text)
    extensions = ["fenced_code", "tables", "codehilite", "sane_lists"]
    ext_cfg = {"codehilite": {"css_class": "highlight", "linenums": False}}
    converter = md_lib.Markdown(extensions=extensions, extension_configs=ext_cfg)
    html = converter.convert(text)
    converter.reset()
    # Wrap bare <table> tags in scrollable container
    html = re.sub(r"(<table\b)", r'<div class="table-wrap">\1', html)
    html = re.sub(r"(</table>)", r"\1</div>", html)
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
                        f'{title_html}<div class="table-wrap"><table class="data-table">'
                        f"<thead><tr>{header}</tr></thead>"
                        f"<tbody>{''.join(body_rows)}</tbody></table></div>"
                    )
        except Exception as e:
            logger.warning("Failed to render artifact: %s", e)
            continue

    return "\n".join(parts)


def _render_plan_html(execution_log: list[dict]) -> str:
    """Render execution log as a plan summary (successful steps only)."""
    if not execution_log:
        return ""
    # Only show successful steps — skip debug retries, errors, intermediate failures
    successful = [e for e in execution_log if e.get("status") == "success"]
    if not successful:
        return ""
    parts = ['<div class="execution-plan">', "<h4>Execution Steps</h4>", "<ol>"]
    for entry in successful:
        action = html_escape(entry.get("action", "").upper())
        step_num = entry.get("step_number", "?")
        summary = html_escape(str(entry.get("result_summary", ""))[:150])
        parts.append(f'<li class="step-done">[{action}] Step {step_num}: {summary}</li>')
    parts.append("</ol></div>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

def _render_discovery_html(discovery: dict) -> str:
    """Render database discovery section (table overview + ERD diagram)."""
    if not discovery:
        return ""
    table_summary = discovery.get("tableSummary", [])
    erd_mermaid = discovery.get("erdMermaid", "")
    if not table_summary and not erd_mermaid:
        return ""

    parts = ['<div class="discovery-section">']
    parts.append("<h3>Database Overview</h3>")

    if table_summary:
        parts.append('<div class="table-wrap"><table class="data-table">')
        parts.append("<thead><tr><th>Table</th><th>Columns</th><th>Rows</th></tr></thead><tbody>")
        for t in table_summary:
            name = html_escape(str(t.get("name", "")))
            cols = t.get("columns", "")
            rows = t.get("rows")
            rows_str = f"{rows:,}" if rows is not None else "\u2014"
            parts.append(f"<tr><td><code>{name}</code></td><td>{cols}</td><td>{rows_str}</td></tr>")
        parts.append("</tbody></table></div>")

    if erd_mermaid:
        # Output mermaid div — rendered client-side by mermaid.js in the template.
        # For PDF (no JS), try kroki.io for a static image fallback.
        erd_img = _mermaid_to_base64_uri(erd_mermaid, timeout=10.0)
        if erd_img:
            # Image for PDF; hidden in browser when mermaid.js renders the div
            parts.append(f'<div class="erd-diagram erd-img"><img src="{erd_img}" alt="ER Diagram"></div>')
        parts.append(f'<div class="erd-diagram erd-mermaid"><pre class="mermaid">{html_escape(erd_mermaid)}</pre></div>')

    parts.append("</div>")
    return "\n".join(parts)


def generate_html_report(
    turns: list[dict], db_info: str = "", *, discovery: dict | None = None,
) -> str:
    """Generate a self-contained HTML report from conversation turns.

    Each turn: {question, response, artifacts, executionLog, mode, elapsed}
    """
    export_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    turns_html = []
    for i, turn in enumerate(turns):
        exec_log = turn.get("executionLog", [])
        has_code_steps = any(
            e.get("status") == "success" and e.get("code", "").strip()
            for e in exec_log
        )
        turns_html.append({
            "number": i + 1,
            "user_message": html_escape(turn.get("question", "")),
            "ai_message_html": _markdown_to_html(turn.get("response", "")),
            "artifacts_html": _render_artifacts_html(turn.get("artifacts", [])),
            "plan_html": _render_plan_html(exec_log),
            "mode": turn.get("mode", ""),
            "elapsed": turn.get("elapsed", 0),
            "is_cached": not has_code_steps,
        })

    from jinja2 import Template
    template = Template(HTML_REPORT_TEMPLATE)
    return template.render(
        title="MCPDB — Analysis Report",
        db_info=html_escape(db_info),
        export_date=export_date,
        turns=turns_html,
        total_turns=len(turns_html),
        discovery_html=_render_discovery_html(discovery or {}),
    )


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------

def generate_pdf(
    turns: list[dict], db_info: str = "", *, discovery: dict | None = None,
) -> bytes:
    """Generate a PDF from conversation turns. Requires weasyprint."""
    try:
        from weasyprint import HTML
    except ImportError:
        raise ImportError(
            "WeasyPrint is required for PDF export. Install with: pip install weasyprint"
        )
    html_content = generate_html_report(turns, db_info, discovery=discovery)
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
    "excel": [],
}

# Schema introspection queries by database type
_SCHEMA_QUERY = {
    "mysql": (
        "SELECT TABLE_NAME AS `Table`, TABLE_ROWS AS `Rows`\n"
        "FROM information_schema.tables\n"
        "WHERE TABLE_SCHEMA = DATABASE()\n"
        "ORDER BY TABLE_NAME"
    ),
    "postgresql": (
        "SELECT tablename AS \"Table\",\n"
        "       n_live_tup AS \"Rows\"\n"
        "FROM pg_stat_user_tables\n"
        "ORDER BY tablename"
    ),
    "sqlite": (
        "SELECT name AS 'Table'\n"
        "FROM sqlite_master\n"
        "WHERE type = 'table'\n"
        "ORDER BY name"
    ),
}


def _build_db_setup(db_type: str, connection_string: str) -> str:
    """Build the setup code cell for database sources (SQLAlchemy)."""
    packages = DB_DRIVER_PACKAGES.get(db_type, [])
    pip_line = f"!pip install -q sqlalchemy pandas {' '.join(packages)}" if packages else "!pip install -q sqlalchemy pandas"

    return (
        f"# Setup — install packages and connect to database\n"
        f"{pip_line}\n\n"
        f"import pandas as pd\n"
        f"from sqlalchemy import create_engine, text\n\n"
        f'CONNECTION_STRING = "{connection_string}"\n'
        f"engine = create_engine(CONNECTION_STRING)\n\n"
        f"def db_query(sql):\n"
        f'    """Execute SQL and return a DataFrame."""\n'
        f"    with engine.connect() as conn:\n"
        f"        return pd.read_sql(text(sql), conn)\n\n"
        f'print(f"Connected to {{engine.url}}")'
    )


def _build_file_setup(db_type: str, discovery: dict | None) -> str:
    """Build the setup code cell for CSV/Excel sources (DuckDB in-memory).

    The notebook user places their original files in a ``data/`` folder
    next to the notebook.  The setup cell loads every file found by the
    discovery metadata (table_summary) into an in-memory DuckDB database
    and provides the same ``db_query()`` helper used by database notebooks.
    """
    table_summary = (discovery or {}).get("tableSummary", [])

    # Build file loading lines from discovery metadata
    load_lines: list[str] = []
    for t in table_summary:
        name = t.get("name", "")
        if not name:
            continue
        # For CSV: table name is the filename (without extension)
        if db_type == "csv":
            load_lines.append(
                f"con.execute(\"CREATE TABLE {name} AS "
                f"SELECT * FROM read_csv_auto('data/{name}.csv')\")"
            )
        else:  # excel
            load_lines.append(
                f"con.execute(\"CREATE TABLE {name} AS "
                f"SELECT * FROM st_read('data/{name}.xlsx')\")"
            )

    if not load_lines:
        # Fallback: scan data/ folder for files
        if db_type == "csv":
            load_lines.append(
                "import glob\n"
                "for f in sorted(glob.glob('data/*.csv')):\n"
                "    name = Path(f).stem\n"
                "    con.execute(f\"CREATE TABLE {name} AS SELECT * FROM read_csv_auto('{f}')\")\n"
                "    print(f'  Loaded {name}')"
            )
        else:
            load_lines.append(
                "import glob\n"
                "for f in sorted(glob.glob('data/*.xlsx')):\n"
                "    name = Path(f).stem\n"
                "    con.execute(f\"CREATE TABLE {name} AS SELECT * FROM st_read('{f}')\")\n"
                "    print(f'  Loaded {name}')"
            )

    load_code = "\n".join(load_lines)

    install_extra = " openpyxl" if db_type == "excel" else ""
    return (
        f"# Setup — load {db_type.upper()} files into in-memory DuckDB\n"
        f"!pip install -q duckdb pandas{install_extra}\n\n"
        f"import duckdb\n"
        f"import pandas as pd\n"
        f"from pathlib import Path\n\n"
        f"con = duckdb.connect(':memory:')\n\n"
        f"# Load data files (place original files in data/ folder)\n"
        f"{load_code}\n\n"
        f"def db_query(sql):\n"
        f'    """Execute SQL and return a DataFrame."""\n'
        f"    return con.execute(sql).fetchdf()\n\n"
        f"# Show loaded tables\n"
        f"db_query(\"SHOW TABLES\")"
    )


# Schema queries for context-based turns, by database type
_FILE_SCHEMA_QUERY = (
    "SELECT table_name AS 'Table',\n"
    "       estimated_size AS 'Rows'\n"
    "FROM duckdb_tables()\n"
    "ORDER BY table_name"
)


def _notebook_discovery_cells(
    discovery: dict, db_type: str, new_markdown_cell, new_code_cell,
):
    """Build executable notebook cells for database discovery.

    Instead of static markdown, these cells query the live database to
    produce the table overview and ER diagram, so the notebook always
    reflects the current state of the database when re-run.
    """
    cells = []
    table_summary = discovery.get("tableSummary", [])
    erd_mermaid = discovery.get("erdMermaid", "")

    if not table_summary and not erd_mermaid:
        return cells

    is_file_source = db_type in ("csv", "excel")
    cells.append(new_markdown_cell(
        source="## Data Overview" if is_file_source else "## Database Overview"
    ))

    # ── Schema overview code cell ──
    if is_file_source:
        # DuckDB: list tables with row counts and column counts
        schema_sql = (
            "SELECT table_name AS \"Table\",\n"
            "       column_count AS \"Columns\",\n"
            "       estimated_size AS \"Rows\"\n"
            "FROM duckdb_tables()\n"
            "ORDER BY table_name"
        )
    elif db_type == "postgresql":
        schema_sql = (
            "SELECT t.TABLE_NAME AS \"Table\",\n"
            "       COUNT(c.COLUMN_NAME) AS \"Columns\",\n"
            "       s.n_live_tup AS \"Rows\"\n"
            "FROM information_schema.tables t\n"
            "LEFT JOIN information_schema.columns c\n"
            "  ON t.TABLE_NAME = c.TABLE_NAME AND t.TABLE_SCHEMA = c.TABLE_SCHEMA\n"
            "LEFT JOIN pg_stat_user_tables s ON t.TABLE_NAME = s.relname\n"
            "WHERE t.TABLE_SCHEMA = 'public' AND t.TABLE_TYPE = 'BASE TABLE'\n"
            "GROUP BY t.TABLE_NAME, s.n_live_tup\n"
            "ORDER BY t.TABLE_NAME"
        )
    elif db_type == "sqlite":
        schema_sql = (
            "SELECT name AS 'Table' FROM sqlite_master\n"
            "WHERE type = 'table' ORDER BY name"
        )
    else:  # mysql (default)
        schema_sql = (
            "SELECT t.TABLE_NAME AS `Table`,\n"
            "       COUNT(c.COLUMN_NAME) AS `Columns`,\n"
            "       t.TABLE_ROWS AS `Rows`\n"
            "FROM information_schema.tables t\n"
            "LEFT JOIN information_schema.columns c\n"
            "  ON t.TABLE_NAME = c.TABLE_NAME AND t.TABLE_SCHEMA = c.TABLE_SCHEMA\n"
            "WHERE t.TABLE_SCHEMA = DATABASE()\n"
            "GROUP BY t.TABLE_NAME, t.TABLE_ROWS\n"
            "ORDER BY t.TABLE_NAME"
        )

    cells.append(new_code_cell(source=(
        f"# Schema overview — live query of current {'data' if is_file_source else 'database'} state\n"
        f'schema_df = db_query("""\n{schema_sql}\n""")\n'
        f"schema_df.style.hide(axis='index')"
    )))

    # ── ERD code cell ──
    # Use the pre-computed mermaid string from the web app's SchemaExplorer.
    # It includes both explicit FK constraints AND inferred relationships
    # (from column naming patterns like order_id → orders.id), which a simple
    # information_schema query would miss.
    if erd_mermaid and db_type not in ("sqlite", "csv", "excel"):
        # Embed the mermaid code via base64 to avoid any string escaping issues
        # (mermaid ERD contains quotes in relationship labels like "mc_make").
        import base64 as _b64_export
        erd_b64 = _b64_export.b64encode(erd_mermaid.encode()).decode()
        erd_lines = [
            "# Entity-Relationship Diagram (includes inferred relationships)",
            "import base64 as _b64",
            "from IPython.display import display, HTML",
            "",
            f'mermaid_code = _b64.b64decode("{erd_b64}").decode()',
            "",
            "# Render in an iframe with mermaid.js",
            'inner_page = "\\n".join([',
            '    "<!DOCTYPE html><html><head>",',
            '    \'<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>\',',
            '    "<style>",',
            '    "body { margin:0; padding:16px; background:white; font-family:sans-serif; }",',
            '    ".mermaid { text-align:center; }",',
            '    "</style>",',
            '    "</head><body>",',
            '    \'<pre class="mermaid">\',',
            '    mermaid_code,',
            '    "</pre>",',
            '    \'<script>mermaid.initialize({startOnLoad:true, theme:"default"});</script>\',',
            '    "</body></html>",',
            '])',
            'data_url = "data:text/html;base64," + _b64.b64encode(inner_page.encode()).decode()',
            'display(HTML(',
            '    f\'<iframe src="{data_url}" \'',
            '    f\'style="width:100%;height:600px;border:1px solid #e2e8f0;border-radius:8px;background:white" \'',
            '    f\'sandbox="allow-scripts"></iframe>\'',
            '))',
        ]
        cells.append(new_markdown_cell(source="### Entity-Relationship Diagram"))
        cells.append(new_code_cell(source="\n".join(erd_lines)))

    # ── File source: column details (no FK/ERD available) ──
    if is_file_source and table_summary:
        col_detail_lines = [
            "# Column details for each table",
            "for tbl in db_query(\"SHOW TABLES\")[\"name\"]:",
            "    print(f\"\\n=== {tbl} ===\")",
            "    cols = db_query(f\"DESCRIBE {tbl}\")",
            "    display(cols)",
        ]
        cells.append(new_markdown_cell(source="### Column Details"))
        cells.append(new_code_cell(source=(
            "from IPython.display import display\n\n"
            + "\n".join(col_detail_lines)
        )))

    return cells


def generate_notebook(
    turns: list[dict],
    connection_string: str = "",
    db_type: str = "mysql",
    db_info: str = "",
    *,
    discovery: dict | None = None,
) -> bytes:
    """Generate a re-runnable Jupyter notebook from conversation turns.

    The notebook reproduces the full computation history: each successful
    SQL query and Python code block becomes an executable cell.  Running
    the notebook end-to-end produces the same results as the web client.
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
    db_label = db_info or db_type

    # ── Title ──
    is_file_source = db_type in ("csv", "excel")
    title_parts = [
        f"# MCPDB Analysis — {db_label}\n",
        f"Exported: {export_date} &nbsp;|&nbsp; Turns: {len(turns)}\n",
        "This notebook reproduces the full computation pipeline from the MCPDB session.  ",
        "Run **Cell 1 (Setup)** first, then execute cells top-to-bottom to regenerate all results.",
    ]
    if is_file_source:
        title_parts.append(
            f"\n> **Note:** This analysis was run on uploaded {db_type.upper()} files.  "
            "> Place the original files in a `data/` folder next to this notebook,  "
            "> then update the file paths in the setup cell if needed."
        )
    else:
        title_parts.append(
            "\n> **Security Notice:** This notebook contains database connection credentials.  "
            "> Remove the `CONNECTION_STRING` value before sharing."
        )
    nb.cells.append(new_markdown_cell(source="\n".join(title_parts)))

    # ── Setup cell (must come before discovery which uses db_query) ──
    if is_file_source:
        setup_code = _build_file_setup(db_type, discovery)
    else:
        setup_code = _build_db_setup(db_type, connection_string)
    nb.cells.append(new_code_cell(source=setup_code))

    # ── Discovery (table overview + ERD) — executable code cells ──
    if discovery:
        nb.cells.extend(_notebook_discovery_cells(discovery, db_type, new_markdown_cell, new_code_cell))

    # ── Turn cells ──
    for i, turn in enumerate(turns):
        question = turn.get("question", "")
        response = turn.get("response", "")
        exec_log = turn.get("executionLog", [])
        mode = turn.get("mode", "")

        # Turn header — show question as a distinct markdown block
        header_parts = [f"## Question {i + 1}"]
        if mode:
            header_parts.append(f"*Mode: {mode}*")
        header_parts.append(f"\n> {question}")
        nb.cells.append(new_markdown_cell(source="\n".join(header_parts)))

        # Collect successful code steps
        code_steps = [
            e for e in exec_log
            if e.get("status") == "success" and e.get("code", "").strip()
        ]

        if not code_steps:
            # Context-based answer — generate a schema query so the notebook
            # produces live data when re-run (instead of stale markdown).
            if is_file_source:
                schema_sql = _FILE_SCHEMA_QUERY
            else:
                schema_sql = _SCHEMA_QUERY.get(db_type, _SCHEMA_QUERY["mysql"])
            nb.cells.append(new_code_cell(source=(
                f"# Context-based answer: {question}\n"
                f"# The agent answered this from schema metadata. "
                f"Run to see current data.\n"
                f'db_query("""\n{schema_sql}\n""").style.hide(axis="index")'
            )))
            continue

        # Each successful step becomes an executable code cell
        for j, entry in enumerate(code_steps):
            action = entry.get("action", "")
            code = entry.get("code", "")
            step_num = entry.get("step_number", j + 1)

            if action == "sql":
                sql_code = code.strip()
                if '"""' in sql_code:
                    sql_code = sql_code.replace('"""', "'''")
                cell_code = f"# Step {step_num}: SQL query\ndf = db_query(\"\"\"\n{sql_code}\n\"\"\")\ndf.style.hide(axis='index')"
            elif action == "python":
                cell_code = f"# Step {step_num}: Python\n{code}"
            else:
                cell_code = f"# Step {step_num}: {action}\n{code}"

            nb.cells.append(new_code_cell(source=cell_code))

    # ── Footer ──
    nb.cells.append(new_markdown_cell(
        source=f"---\n*Generated by [MCPDB](https://github.com/korobool/mcpdb) on {export_date}*"
    ))

    return nbformat.writes(nb, version=4).encode("utf-8")


# ---------------------------------------------------------------------------
# Jupyter server management
# ---------------------------------------------------------------------------

from pathlib import Path

_JUPYTER_PORT = 18888  # Dedicated port — avoids conflicts with user's Jupyter
_jupyter_proc = None


def _upload_notebook_via_api(port: int, filename: str, nb_bytes: bytes) -> bool:
    """Upload a notebook to a running Jupyter server via its REST API."""
    try:
        payload = _json.dumps({
            "type": "notebook",
            "content": _json.loads(nb_bytes.decode("utf-8")),
        }).encode("utf-8")
        url = f"http://127.0.0.1:{port}/api/contents/{filename}"
        req = urllib.request.Request(
            url, data=payload, method="PUT",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status in (200, 201)
    except Exception as e:
        logger.warning("Jupyter API upload failed: %s", e)
        return False


def start_jupyter_and_open(notebook_bytes: bytes, filename: str = "") -> str:
    """Save notebook, start Jupyter if needed, return URL.

    Uses a dedicated port (18888) so it never conflicts with the user's
    own Jupyter instances. Uploads the notebook via the REST API if the
    server is already running.
    """
    import socket
    import subprocess
    import sys
    import time

    global _jupyter_proc

    nb_dir = Path.home() / ".mcpdb" / "jupyter"
    nb_dir.mkdir(parents=True, exist_ok=True)

    if not filename:
        filename = f"mcpdb_{datetime.now().strftime('%Y%m%d_%H%M%S')}.ipynb"

    port = _JUPYTER_PORT

    # Check if our tracked process is still alive
    if _jupyter_proc is not None and _jupyter_proc.poll() is not None:
        _jupyter_proc = None

    # Check if something (our server or a leftover) is listening on our port
    server_running = False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            server_running = True
    except OSError:
        pass

    if server_running:
        # Upload notebook via REST API — works regardless of notebook-dir
        if _upload_notebook_via_api(port, filename, notebook_bytes):
            return f"http://localhost:{port}/notebooks/{filename}"
        # API upload failed — fall back to saving to disk
        logger.warning("API upload failed, saving to disk instead")

    # Save notebook to disk
    nb_path = nb_dir / filename
    nb_path.write_bytes(notebook_bytes)

    # Sign notebook for trust
    try:
        import nbformat as _nbformat
        from nbformat.sign import NotebookNotary
        nb = _nbformat.read(str(nb_path), as_version=4)
        NotebookNotary().sign(nb)
        _nbformat.write(nb, str(nb_path))
    except Exception as e:
        logger.warning("Failed to sign notebook: %s", e)

    if not server_running:
        # Start our own Jupyter server
        _jupyter_proc = subprocess.Popen(
            [
                sys.executable, "-m", "jupyter", "notebook",
                "--no-browser",
                f"--port={port}",
                f"--notebook-dir={nb_dir}",
                "--NotebookApp.token=",
                "--NotebookApp.password=",
                "--NotebookApp.disable_check_xsrf=True",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for startup
        for _ in range(30):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(0.5)

    return f"http://localhost:{port}/notebooks/{filename}"


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
.table-wrap { overflow-x: auto; margin: 14px 0; }
.data-table, .ai-response table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table thead th, .ai-response table thead th {
    background: #2563eb; color: white; padding: 10px 12px; text-align: left; font-weight: 600; white-space: nowrap;
}
.data-table tbody td, .ai-response table tbody td { padding: 8px 12px; border-bottom: 1px solid #e2e8f0; white-space: nowrap; }
.data-table tbody tr:nth-child(even), .ai-response table tbody tr:nth-child(even) { background: #f8fafc; }
.data-table tbody tr:hover, .ai-response table tbody tr:hover { background: #eff6ff; }
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
.cached-badge {
    display: inline-block; background: #fef3c7; color: #92400e; font-size: 11px; font-weight: 600;
    padding: 2px 8px; border-radius: 10px; margin-left: 8px; vertical-align: middle;
}
.discovery-section {
    background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08);
    padding: 20px 24px; margin-bottom: 20px;
}
.discovery-section h3 { margin: 0 0 12px 0; color: #1e293b; font-size: 18px; }
.discovery-section .erd-diagram { text-align: center; margin-top: 16px; }
.discovery-section .erd-diagram img { max-width: 100%; height: auto; border-radius: 6px; border: 1px solid #e2e8f0; }
.erd-mermaid pre.mermaid { text-align: center; background: none; color: inherit; }
/* When mermaid.js renders, hide the static image fallback */
.erd-mermaid[data-processed="true"] ~ .erd-img, .erd-mermaid svg ~ .erd-img { display: none; }
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
{% if discovery_html %}
{{ discovery_html }}
{% endif %}
{% for turn in turns %}
<div class="turn">
    <div class="user-message">
        <div class="label">Question {{ turn.number }}{% if turn.is_cached %}<span class="cached-badge">context-based</span>{% endif %}</div>
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

<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>
mermaid.initialize({ startOnLoad: true, theme: 'default', securityLevel: 'strict' });
// Hide static image fallback once mermaid renders
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.erd-mermaid').forEach(function(el) {
        if (el.querySelector('svg')) {
            var img = el.parentElement.querySelector('.erd-img');
            if (img) img.style.display = 'none';
        }
    });
});
</script>
</body>
</html>
"""
