"""Artifact viewer — display tables, charts, and other results."""

from __future__ import annotations

import base64
import logging
from typing import Any, TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from mcpdb.ui.state import UIState

logger = logging.getLogger("mcpdb.ui.artifact_viewer")


def create_artifact_viewer(state: UIState) -> None:
    """Create the artifact display panel."""
    container = ui.column().classes("w-full gap-2")

    def refresh() -> None:
        container.clear()
        if not state.artifacts:
            return

        with container:
            ui.label(f"Results ({len(state.artifacts)})").classes(
                "text-sm font-bold"
            )

            for i, artifact in enumerate(state.artifacts):
                atype = artifact.get("type", "unknown")
                title = artifact.get("title", f"Result {i + 1}")

                with ui.expansion(title, icon="table_chart" if atype == "table" else "image").classes("w-full"):
                    if atype == "table":
                        _render_table(artifact.get("data", {}))
                    elif atype == "chart":
                        _render_chart(artifact.get("data", {}))
                    else:
                        ui.label(f"Unknown artifact type: {atype}")

    state.on_update(refresh)
    refresh()


def _render_table(data: dict[str, Any]) -> None:
    """Render a table artifact as a NiceGUI table."""
    columns = data.get("columns", [])
    rows = data.get("rows", [])
    total = data.get("total_rows", len(rows))

    if not columns:
        ui.label("(empty table)")
        return

    table_columns = [
        {"name": str(c), "label": str(c), "field": str(c), "align": "left"}
        for c in columns
    ]
    table_rows = [
        {str(c): str(v) for c, v in zip(columns, row)} for row in rows[:50]
    ]

    ui.table(
        columns=table_columns,
        rows=table_rows,
        pagination=10,
    ).classes("w-full")

    if total > 50:
        ui.label(f"Showing 50 of {total} rows").classes("text-xs text-gray-400")


def _render_chart(data: dict[str, Any]) -> None:
    """Render a chart artifact as an image."""
    b64 = data.get("image_base64", "")
    fmt = data.get("format", "png")

    if not b64:
        ui.label("(no chart data)")
        return

    ui.image(f"data:image/{fmt};base64,{b64}").classes("w-full max-w-lg")
