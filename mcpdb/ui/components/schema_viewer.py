"""Schema viewer — interactive tree view of tables, columns, and types."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from mcpdb.ui.state import UIState

logger = logging.getLogger("mcpdb.ui.schema_viewer")


def create_schema_viewer(state: UIState) -> None:
    """Create an interactive schema explorer panel."""
    container = ui.column().classes("w-full gap-2")

    def refresh() -> None:
        container.clear()
        sources = state.registry.list_sources()
        if not sources:
            with container:
                ui.label("No sources connected").classes("text-gray-400 text-sm italic")
            return

        with container:
            for meta in sources:
                with ui.expansion(
                    f"{meta.display_name} ({meta.source_type.value})",
                    icon="storage",
                ).classes("w-full"):
                    ui.label(f"Source ID: {meta.source_id}").classes("text-xs text-gray-400")
                    ui.label(f"Tables: {len(meta.tables)}").classes("text-xs text-gray-400")

                    for table in meta.tables:
                        with ui.expansion(
                            f"{table.name} ({table.row_count or '?'} rows)",
                            icon="table_chart",
                        ).classes("w-full ml-4"):
                            # Column list
                            table_cols = [
                                {"name": "col", "label": "Column", "field": "col", "align": "left"},
                                {"name": "type", "label": "Type", "field": "type", "align": "left"},
                                {"name": "nullable", "label": "Nullable", "field": "nullable", "align": "center"},
                            ]
                            table_rows = [
                                {
                                    "col": col.name,
                                    "type": col.dtype,
                                    "nullable": "Yes" if col.nullable else "No",
                                }
                                for col in table.columns
                            ]
                            ui.table(
                                columns=table_cols,
                                rows=table_rows,
                            ).classes("w-full").props("dense flat")

                            # Primary keys
                            if table.primary_keys:
                                ui.label(
                                    f"PK: {', '.join(table.primary_keys)}"
                                ).classes("text-xs text-blue-400 mt-1")

                            # Indexes
                            if table.indexes:
                                for idx in table.indexes:
                                    cols = idx.get("columns", [])
                                    unique = "UNIQUE " if idx.get("unique") else ""
                                    ui.label(
                                        f"IDX: {unique}{idx.get('name', '?')} ({', '.join(cols)})"
                                    ).classes("text-xs text-gray-400")

                            # Sample button
                            def show_sample(t=table, m=meta) -> None:
                                _load_sample(state, m.source_id, t.name)

                            ui.button(
                                "Sample Rows", icon="visibility", on_click=show_sample,
                            ).props("flat dense size=sm").classes("mt-1")

    state.on_update(refresh)
    refresh()


def _load_sample(state: UIState, source_id: str, table_name: str) -> None:
    """Load sample rows from a table and display in a dialog."""
    try:
        from mcpdb.sources.base import QueryableSource
        source = state.registry.get_source(source_id)
        if not isinstance(source, QueryableSource):
            ui.notify(f"Source is not queryable", type="warning")
            return

        df = source.get_sample(table_name, limit=10)
        columns = [
            {"name": str(c), "label": str(c), "field": str(c), "align": "left"}
            for c in df.columns
        ]
        rows = [
            {str(c): str(v) for c, v in zip(df.columns, row)}
            for row in df.values[:10]
        ]

        with ui.dialog() as dialog, ui.card().classes("w-full max-w-4xl"):
            ui.label(f"Sample: {table_name}").classes("text-lg font-bold")
            ui.table(columns=columns, rows=rows, pagination=10).classes("w-full")
            ui.button("Close", on_click=dialog.close).classes("mt-2")
        dialog.open()

    except Exception as e:
        ui.notify(f"Error loading sample: {e}", type="negative")
