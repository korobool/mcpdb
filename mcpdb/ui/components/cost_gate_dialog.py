"""Cost gate dialog — strategy selection for expensive queries."""

from __future__ import annotations

import logging
from typing import Any, Callable, TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from mcpdb.ui.state import UIState

logger = logging.getLogger("mcpdb.ui.cost_gate")


class CostGateDialog:
    """Modal dialog for cost gate strategy selection.

    Displays cost analysis and lets the user choose:
    - SAMPLE: Run on a sample of the data
    - FULL: Run the full query (may be slow/expensive)
    - CANCEL: Abort the query
    """

    def __init__(self) -> None:
        self._dialog = None
        self._callback: Callable[[str], None] | None = None

    def show(
        self,
        cost_analysis: dict[str, Any],
        on_strategy: Callable[[str], None],
    ) -> None:
        """Show the cost gate dialog with analysis details."""
        self._callback = on_strategy

        with ui.dialog() as self._dialog, ui.card().classes("w-full max-w-lg"):
            ui.label("Query Cost Warning").classes("text-xl font-bold text-orange-400")
            ui.separator()

            # Cost details
            with ui.column().classes("gap-2 w-full"):
                estimated_rows = cost_analysis.get("estimated_rows", "unknown")
                scan_type = cost_analysis.get("scan_type", "unknown")
                tables = cost_analysis.get("tables_involved", [])
                reason = cost_analysis.get("reason", "Query may be expensive")

                ui.label(reason).classes("text-sm")

                with ui.card().classes("w-full p-3 bg-gray-800"):
                    ui.label(f"Estimated rows: {estimated_rows:,}" if isinstance(estimated_rows, int) else f"Estimated rows: {estimated_rows}").classes("text-sm")
                    ui.label(f"Scan type: {scan_type}").classes("text-sm")
                    if tables:
                        ui.label(f"Tables: {', '.join(tables)}").classes("text-sm")

            ui.separator()

            # Strategy buttons
            ui.label("Choose a strategy:").classes("font-medium")

            with ui.row().classes("gap-2 w-full justify-center"):
                ui.button(
                    "Sample (5%)",
                    icon="science",
                    on_click=lambda: self._select("SAMPLE"),
                    color="blue",
                ).classes("flex-1").props("unelevated")

                ui.button(
                    "Full Query",
                    icon="play_arrow",
                    on_click=lambda: self._select("FULL"),
                    color="orange",
                ).classes("flex-1").props("unelevated")

                ui.button(
                    "Cancel",
                    icon="cancel",
                    on_click=lambda: self._select("CANCEL"),
                    color="red",
                ).classes("flex-1").props("outline")

            # Explanation
            with ui.expansion("What do these mean?", icon="help").classes("w-full"):
                ui.markdown(
                    "- **Sample**: Runs on ~5% of the data. Fast but approximate.\n"
                    "- **Full**: Runs the complete query. May take longer.\n"
                    "- **Cancel**: Aborts this query entirely."
                ).classes("text-sm")

        self._dialog.open()

    def _select(self, strategy: str) -> None:
        """Handle strategy selection."""
        if self._dialog:
            self._dialog.close()
        if self._callback:
            self._callback(strategy)

    def close(self) -> None:
        """Close the dialog if open."""
        if self._dialog:
            self._dialog.close()
