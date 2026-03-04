"""Excel viewer — cell grid rendering with formula toggle."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from mcpdb.ui.state import UIState

logger = logging.getLogger("mcpdb.ui.excel_viewer")


def create_excel_viewer(state: UIState) -> None:
    """Create an Excel workbook viewer panel."""
    container = ui.column().classes("w-full gap-2")

    def refresh() -> None:
        container.clear()
        sources = state.registry.list_sources()
        excel_sources = [
            s for s in sources if s.source_type.value == "excel"
        ]

        if not excel_sources:
            return

        with container:
            ui.label("Excel Workbooks").classes("text-sm font-bold")

            for meta in excel_sources:
                source = state.registry.get_source(meta.source_id)

                with ui.expansion(
                    meta.display_name, icon="description",
                ).classes("w-full"):
                    sheets = source.list_sheets()
                    for sheet in sheets:
                        _create_sheet_view(source, sheet, meta.source_id)

    state.on_update(refresh)
    refresh()


def _create_sheet_view(source: Any, sheet: dict, source_id: str) -> None:
    """Create a view for a single sheet."""
    name = sheet["name"]
    stype = sheet.get("structure_type", "unknown")
    ntables = sheet.get("tables", 0)
    ntext = sheet.get("text_regions", 0)

    with ui.expansion(
        f"{name} ({stype}, {ntables} table(s), {ntext} text region(s))",
        icon="grid_on",
    ).classes("w-full"):
        # Toggle for formulas
        show_formulas = ui.checkbox("Show Formulas").classes("text-sm")

        # Cell grid display
        grid_container = ui.column().classes("w-full")

        def load_grid() -> None:
            grid_container.clear()
            with grid_container:
                try:
                    text = source.read_range(
                        name,
                        include_formulas=show_formulas.value,
                    )
                    ui.code(text).classes("w-full text-xs").props("wrap")
                except Exception as e:
                    ui.label(f"Error: {e}").classes("text-red-400")

        show_formulas.on("change", lambda: load_grid())
        load_grid()

        # Structure info
        try:
            structure = source.get_sheet_structure(name)
            with ui.expansion("Structure Analysis", icon="analytics").classes("w-full"):
                ui.markdown(structure).classes("text-sm")
        except Exception:
            pass

        # Formulas list
        try:
            formulas = source.get_formulas(name)
            if formulas:
                with ui.expansion(
                    f"Formulas ({len(formulas)})", icon="functions",
                ).classes("w-full"):
                    for f in formulas[:30]:
                        ui.label(f"{f['cell']}: {f['formula']}").classes(
                            "text-xs font-mono"
                        )
                    if len(formulas) > 30:
                        ui.label(f"... {len(formulas) - 30} more").classes(
                            "text-xs text-gray-400"
                        )
        except Exception:
            pass
