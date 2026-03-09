"""Rich result rendering for mcpdb CLI."""

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

_CHART_DIR = Path.home() / ".mcpdb" / "charts"


def save_chart_artifact(artifact: dict[str, Any]) -> Path | None:
    """Save a chart artifact to disk and return the file path (or None).

    Charts are saved as PNG files under ``~/.mcpdb/charts/``.
    """
    import json as _json

    data = artifact.get("data", {})
    if isinstance(data, str):
        try:
            data = _json.loads(data)
        except (_json.JSONDecodeError, ValueError):
            data = {}

    b64 = data.get("image_base64", "")
    if not b64:
        return None

    fmt = data.get("format", "png")
    title = artifact.get("title", "chart")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_title = "".join(c if c.isalnum() or c in "_-" else "_" for c in title)[:60]
    filename = f"{ts}_{safe_title}.{fmt}"

    _CHART_DIR.mkdir(parents=True, exist_ok=True)
    path = _CHART_DIR / filename
    path.write_bytes(base64.b64decode(b64))
    return path


class ResultRenderer:
    """Renders agent results with Rich formatting."""

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()

    def render_response(
        self,
        response: str,
        followups: list[str] | None = None,
    ) -> None:
        """Render the full agent response with optional follow-up suggestions."""
        if not response:
            self._console.print("[dim]No response generated.[/dim]")
            return

        # Render response as Rich Markdown
        md = Markdown(response)
        self._console.print(md)

        if followups:
            self._console.print()
            self.render_followups(followups)

    def render_followups(self, followups: list[str]) -> None:
        """Render follow-up suggestions as numbered list."""
        self._console.print("[dim]Suggestions:[/dim]")
        for i, fup in enumerate(followups, 1):
            self._console.print(f"  [cyan]\\[{i}][/cyan] {fup}")

    def render_error(self, error: str, detail: str = "") -> None:
        """Render an error in a red panel."""
        body = f"[red]{error}[/red]"
        if detail:
            body += f"\n[dim]{detail}[/dim]"
        self._console.print(Panel(body, title="Error", border_style="red"))

    def render_artifacts(self, artifacts: list[dict[str, Any]]) -> None:
        """Render execution artifacts (tables, charts).

        Charts are saved as PNG files under ``~/.mcpdb/charts/`` and the
        full path is printed so the user can open them manually.
        """
        for artifact in artifacts:
            atype = artifact.get("type", "")
            if atype == "table":
                self._render_table_artifact(artifact)
            elif atype == "chart":
                path = save_chart_artifact(artifact)
                if path:
                    self._console.print(f"  [bold green]📊 Chart saved:[/bold green] {path}")
                else:
                    self._console.print("[dim](Empty chart artifact)[/dim]")

    def _render_table_artifact(self, artifact: dict[str, Any]) -> None:
        """Render a table artifact using Rich Table."""
        columns = artifact.get("columns", [])
        rows = artifact.get("rows", [])

        if not columns or not rows:
            return

        table = Table(show_lines=False)
        for col in columns:
            table.add_column(str(col))

        max_rows = 20
        for row in rows[:max_rows]:
            table.add_row(*[str(v) for v in row])

        if len(rows) > max_rows:
            table.add_row(*["..." for _ in columns])

        self._console.print(table)

    def render_schema(self, metadata: Any) -> None:
        """Render source schema as a Rich table."""
        tables = getattr(metadata, "tables", [])
        if not tables:
            self._console.print("[dim]No tables found.[/dim]")
            return

        self._console.print(f"[bold]{metadata.display_name}[/bold] ({metadata.source_type.value})")
        self._console.print()

        for tinfo in tables:
            table = Table(title=tinfo.name, show_lines=False)
            table.add_column("Column", style="cyan")
            table.add_column("Type")
            table.add_column("Nullable")
            for col in tinfo.columns:
                nullable = "✓" if col.nullable else ""
                table.add_row(col.name, col.dtype, nullable)
            row_info = f" ({tinfo.row_count} rows)" if tinfo.row_count is not None else ""
            self._console.print(table)
            if row_info:
                self._console.print(f"  [dim]{row_info}[/dim]")
            self._console.print()

    def render_table_list(self, metadata: Any) -> None:
        """Render a compact list of tables with row counts."""
        tables = getattr(metadata, "tables", [])
        if not tables:
            self._console.print("[dim]No tables found.[/dim]")
            return

        table = Table(show_header=True, show_lines=False)
        table.add_column("Table", style="cyan")
        table.add_column("Columns", justify="right")
        table.add_column("Rows", justify="right")

        for tinfo in tables:
            cols = str(len(tinfo.columns))
            rows = str(tinfo.row_count) if tinfo.row_count is not None else "?"
            table.add_row(tinfo.name, cols, rows)

        self._console.print(table)
