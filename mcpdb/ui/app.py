"""Main NiceGUI application with routing and layout."""

from __future__ import annotations

import logging
import warnings

warnings.filterwarnings("ignore", message=".*urllib3.*")
warnings.filterwarnings("ignore", message=".*chardet.*")
warnings.filterwarnings("ignore", message=".*google.generativeai.*")

from nicegui import app, ui

from mcpdb.config import McpdbConfig, load_config
from mcpdb.ui.state import UIState
from mcpdb.ui.theme import get_theme

logger = logging.getLogger("mcpdb.ui.app")

# Global UI state
_state: UIState | None = None
_config: McpdbConfig | None = None


def get_state() -> UIState:
    """Get or create the global UI state."""
    global _state
    if _state is None:
        _state = UIState(config=_config or load_config())
    return _state


def create_app(theme_name: str = "dark", config: McpdbConfig | None = None) -> None:
    """Create and configure the NiceGUI application."""
    global _config
    if config is not None:
        _config = config
    theme = get_theme(theme_name)

    @ui.page("/")
    def main_page() -> None:
        state = get_state()

        ui.dark_mode(theme.name == "dark")

        ui.add_head_html("""
        <!-- KaTeX -->
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
        <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
        <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"></script>

        <!-- Mermaid -->
        <script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
        <script>
        document.addEventListener('DOMContentLoaded', function() {
            mermaid.initialize({startOnLoad: false, theme: 'dark', securityLevel: 'loose'});
        });
        </script>

        <style>
            body { font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; }
            .q-card { border-radius: 8px !important; }
            .nicegui-markdown img { max-width: 100%; height: auto; }
            .mermaid-container { background: transparent; text-align: center; }
            .mermaid-container svg { max-width: 100%; height: auto; }
            .katex-display { overflow-x: auto; overflow-y: hidden; }
            /* Three-column layout */
            #mcpdb-layout { display: flex; height: calc(100vh - 64px); }
            #mcpdb-left { width: 320px; flex-shrink: 0; overflow-y: auto;
                          border-right: 1px solid #374151; padding: 12px; }
            #mcpdb-center { flex: 1; min-width: 0; display: flex;
                            flex-direction: column; position: relative; }
            #mcpdb-right { width: 320px; flex-shrink: 0; overflow-y: auto;
                           border-left: 1px solid #374151; padding: 12px; }
            /* Chat layout inside center */
            #mcpdb-messages { flex: 1; overflow-y: auto; padding: 16px; min-height: 0; }
            #mcpdb-input { flex-shrink: 0; border-top: 1px solid #374151;
                           padding: 16px; display: flex; align-items: flex-end; gap: 8px; }
        </style>
        """)

        # App bar
        with ui.header().classes("items-center justify-between px-4 bg-gray-900"):
            ui.label("MCPDB").classes("text-xl font-bold")
            with ui.row().classes("items-center gap-2"):
                ui.label("Database Explorer").classes("text-sm text-gray-400")

        # Main three-column layout using raw HTML ids for reliable CSS
        with ui.element("div").props('id="mcpdb-layout"'):

            # Left sidebar
            with ui.element("div").props('id="mcpdb-left"'):
                from mcpdb.ui.components.llm_selector import create_llm_selector
                create_llm_selector(state)

                ui.separator().classes("my-2")

                from mcpdb.ui.components.source_panel import create_source_panel
                create_source_panel(state)

                ui.separator().classes("my-2")

                from mcpdb.ui.components.schema_viewer import create_schema_viewer
                create_schema_viewer(state)

                ui.separator().classes("my-2")

                from mcpdb.ui.components.excel_viewer import create_excel_viewer
                create_excel_viewer(state)

            # Center — chat
            with ui.element("div").props('id="mcpdb-center"'):
                from mcpdb.ui.pages.chat import create_chat_page
                create_chat_page(state)

            # Right sidebar
            with ui.element("div").props('id="mcpdb-right"'):
                from mcpdb.ui.components.execution_monitor import create_execution_monitor
                create_execution_monitor(state)

                ui.separator().classes("my-2")

                from mcpdb.ui.components.deep_analysis_viewer import create_deep_analysis_viewer
                create_deep_analysis_viewer(state)

                ui.separator().classes("my-2")

                from mcpdb.ui.components.artifact_viewer import create_artifact_viewer
                create_artifact_viewer(state)


def run_ui(host: str = "0.0.0.0", port: int = 8080, theme: str = "dark",
           config: McpdbConfig | None = None) -> None:
    """Start the MCPDB UI server."""
    create_app(theme_name=theme, config=config)
    ui.run(
        host=host,
        port=port,
        title="MCPDB — Database Explorer",
        favicon="🔍",
        reload=False,
    )
