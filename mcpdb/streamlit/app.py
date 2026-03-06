"""MCPDB Streamlit webchat — main entry point.

This is a **pure MCP client**. It has zero imports from mcpdb.agent,
mcpdb.sources, mcpdb.llm, or any server internals. All interaction
goes through the MCP protocol.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import streamlit as st

from mcpdb.streamlit.mcp_client import McpClientError, McpdbClient
from mcpdb.streamlit.state import (
    get_client,
    init_session_state,
    set_client,
)

logger = logging.getLogger(__name__)

_CSS_PATH = Path(__file__).parent / "styles" / "main.css"


def _load_css() -> None:
    """Inject custom CSS."""
    if _CSS_PATH.exists():
        st.markdown(f"<style>{_CSS_PATH.read_text()}</style>", unsafe_allow_html=True)


@st.cache_resource
def _create_mcp_client() -> McpdbClient:
    """Create and persist the MCP client across Streamlit reruns.

    The client (and the MCPDB server subprocess it manages) lives for the
    entire Streamlit session thanks to ``@st.cache_resource``.
    """
    return McpdbClient()


def _ensure_connected() -> McpdbClient:
    """Start MCP server, auto-connect database from env if available.

    All heavy work (spawn subprocess, connect DB, refresh sources) happens
    once — guarded by ``client.connected`` and ``st.session_state.initialized``.
    """
    client = _create_mcp_client()
    set_client(client)

    if not client.connected:
        db_url = os.environ.get("MCPDB_DATABASE_URL")
        try:
            client.connect(db_url=db_url)
            logger.info("MCP server started")
        except McpClientError as exc:
            st.error(f"Failed to start MCP server: {exc}")
            return client

    # One-time auto-connect: if env var is set and we haven't initialized yet
    if not st.session_state.get("initialized") and client.connected:
        db_url = os.environ.get("MCPDB_DATABASE_URL")
        if db_url:
            try:
                client.connect_database(db_url)
                logger.info("Auto-connected database from MCPDB_DATABASE_URL")
            except McpClientError:
                pass  # may already be connected
            from mcpdb.streamlit.components.sidebar import _refresh_sources
            _refresh_sources(client)
        st.session_state["initialized"] = True

    return client


# ---------------------------------------------------------------------------
# Page render functions (used as callables by st.navigation)
# ---------------------------------------------------------------------------

def _page_chat() -> None:
    from mcpdb.streamlit.pages.chat import render
    render()


def _page_history() -> None:
    from mcpdb.streamlit.pages.history import render
    render()


def _page_explorer() -> None:
    from mcpdb.streamlit.pages.explorer import render
    render()


def _page_settings() -> None:
    from mcpdb.streamlit.pages.settings import render
    render()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Main Streamlit app entry point."""
    st.set_page_config(
        page_title="MCPDB",
        page_icon=":material/database:",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    _load_css()
    init_session_state()
    _ensure_connected()

    # Page routing via st.navigation with callable pages
    nav = st.navigation([
        st.Page(_page_chat, title="Chat", icon=":material/chat:", default=True),
        st.Page(_page_history, title="History", icon=":material/history:"),
        st.Page(_page_explorer, title="Explorer", icon=":material/schema:"),
        st.Page(_page_settings, title="Settings", icon=":material/settings:"),
    ])
    nav.run()


def _find_available_port(start: int, end: int) -> int:
    """Find an available TCP port in the given range."""
    import socket
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No available port in range {start}-{end}")


def run_webchat(port: int | None = None) -> None:
    """Launch the Streamlit app programmatically (called from CLI)."""
    import sys
    import subprocess

    if port is None:
        port = _find_available_port(8501, 8599)

    app_path = str(Path(__file__).resolve())

    cmd = [
        sys.executable, "-m", "streamlit", "run", app_path,
        "--server.port", str(port),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]

    # Pass through environment
    subprocess.run(cmd, env=os.environ.copy())


if __name__ == "__main__":
    main()
