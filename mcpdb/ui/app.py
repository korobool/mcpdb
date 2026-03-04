"""Main NiceGUI application with routing and layout."""

from __future__ import annotations

import logging

from nicegui import app, ui

from mcpdb.ui.state import UIState
from mcpdb.ui.theme import get_theme

logger = logging.getLogger("mcpdb.ui.app")

# Global UI state
_state: UIState | None = None


def get_state() -> UIState:
    """Get or create the global UI state."""
    global _state
    if _state is None:
        _state = UIState()
    return _state


def create_app(theme_name: str = "dark") -> None:
    """Create and configure the NiceGUI application."""
    theme = get_theme(theme_name)

    @ui.page("/")
    def main_page() -> None:
        state = get_state()

        # Apply dark mode
        ui.dark_mode(theme.name == "dark")

        # Custom CSS
        ui.add_head_html(f"""
        <style>
            body {{ font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; }}
            .q-card {{ border-radius: 8px !important; }}
        </style>
        """)

        # App bar
        with ui.header().classes("items-center justify-between px-4 bg-gray-900"):
            ui.label("MCPDB").classes("text-xl font-bold")
            with ui.row().classes("items-center gap-2"):
                ui.label("Database Explorer").classes("text-sm text-gray-400")

        # Main layout: sidebar + content
        with ui.row().classes("w-full h-[calc(100vh-64px)]"):
            # Left sidebar — source panel + schema viewer
            with ui.column().classes(
                "w-80 h-full border-r border-gray-700 p-3 overflow-y-auto"
            ):
                from mcpdb.ui.components.source_panel import create_source_panel
                create_source_panel(state)

                ui.separator().classes("my-2")

                from mcpdb.ui.components.schema_viewer import create_schema_viewer
                create_schema_viewer(state)

                ui.separator().classes("my-2")

                from mcpdb.ui.components.excel_viewer import create_excel_viewer
                create_excel_viewer(state)

            # Center — chat
            with ui.column().classes("flex-grow h-full"):
                from mcpdb.ui.pages.chat import create_chat_page
                create_chat_page(state)

            # Right sidebar — execution monitor + deep analysis + artifacts
            with ui.column().classes(
                "w-80 h-full border-l border-gray-700 p-3 overflow-y-auto"
            ):
                from mcpdb.ui.components.execution_monitor import create_execution_monitor
                create_execution_monitor(state)

                ui.separator().classes("my-2")

                from mcpdb.ui.components.deep_analysis_viewer import create_deep_analysis_viewer
                create_deep_analysis_viewer(state)

                ui.separator().classes("my-2")

                from mcpdb.ui.components.artifact_viewer import create_artifact_viewer
                create_artifact_viewer(state)


def run_ui(host: str = "0.0.0.0", port: int = 8080, theme: str = "dark") -> None:
    """Start the MCPDB UI server."""
    create_app(theme_name=theme)
    ui.run(
        host=host,
        port=port,
        title="MCPDB — Database Explorer",
        favicon="🔍",
        reload=False,
    )
