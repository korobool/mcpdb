"""Sidebar component — source display, connection form, mode picker, controls."""

from __future__ import annotations

import logging
import os
import re

import streamlit as st

from mcpdb.streamlit.mcp_client import McpClientError
from mcpdb.streamlit.state import (
    SourceInfo,
    clear_messages,
    get_active_source,
    get_client,
    get_mode,
    get_sources,
    set_active_source,
    set_error,
    set_followups,
    set_mode,
    set_sources,
)

logger = logging.getLogger(__name__)

MODES = ["auto", "quick", "simple", "optimization", "extended", "deep"]

MODE_DESCRIPTIONS = {
    "auto": "Automatically selects the best mode",
    "quick": "Fast answer from schema context",
    "simple": "Single-pass analysis",
    "optimization": "With validation & replanning",
    "extended": "Multi-revision deep analysis",
    "deep": "Multi-investigation blueprint",
}

_SOURCE_ICONS = {
    "database": ":material/database:",
    "csv": ":material/description:",
    "excel": ":material/table:",
}


def render_sidebar() -> None:
    """Render the full sidebar."""
    with st.sidebar:
        st.title("MCPDB")
        st.caption("Natural language database exploration")

        _render_sources()
        st.divider()
        _render_mode_selector()
        st.divider()
        _render_controls()


# ------------------------------------------------------------------
# Sources
# ------------------------------------------------------------------

def _render_sources() -> None:
    """Connected sources list + add source form."""
    sources = get_sources()
    client = get_client()

    if sources:
        st.subheader(f"Sources ({len(sources)})")
        for src in sources:
            icon = _SOURCE_ICONS.get(src.source_type, ":material/source:")
            details = f" — {src.details}" if src.details else ""
            st.markdown(f"{icon} **{src.name}**{details}")
    else:
        st.subheader("Sources")

    # Add source — always available as expander, collapsed when connected
    with st.expander("Add source" if sources else "Connect database", expanded=not sources):
        conn_str = st.text_input(
            "Connection string",
            placeholder="mysql://user:pass@host/db",
            key="connect_db_input",
        )
        name = st.text_input("Display name (optional)", key="connect_db_name")
        if st.button(
            "Connect",
            key="connect_db_btn",
            disabled=not conn_str or not (client and client.connected),
            use_container_width=True,
        ):
            _do_connect(client, conn_str, name or None)


def _do_connect(client, conn_str: str, name: str | None) -> None:
    """Execute database connection via MCP."""
    try:
        with st.spinner("Connecting..."):
            result = client.connect_database(conn_str, name=name)
        if result.is_error and "already exists" not in result.text:
            st.error(result.text)
            return
        _refresh_sources(client)
        st.rerun()
    except McpClientError as exc:
        if "already exists" not in str(exc):
            st.error(str(exc))
            return
        _refresh_sources(client)
        st.rerun()


def _refresh_sources(client) -> None:
    """Fetch source list from server and update state.

    The server returns plain text lines like:
        - src_1 (database): mydb — 21 tables
    """
    try:
        result = client.list_sources()
        if result.is_error:
            return

        text = result.text.strip()
        if not text or text == "No data sources connected.":
            set_sources([])
            return

        sources = []
        for line in text.splitlines():
            line = line.strip().lstrip("- ")
            if not line:
                continue
            parsed = _parse_source_line(line)
            if parsed:
                sources.append(parsed)

        set_sources(sources)
        if sources and not get_active_source():
            set_active_source(sources[0].source_id)
    except McpClientError:
        logger.warning("Failed to refresh sources", exc_info=True)


def _parse_source_line(line: str) -> SourceInfo | None:
    """Parse a source line from list_sources text output.

    Format: ``src_id (type): display_name — N tables``
    """
    m = re.match(r"(\S+)\s+\((\w+)\):\s+(.+?)(?:\s+—\s+(.*))?$", line)
    if not m:
        return None
    return SourceInfo(
        source_id=m.group(1),
        name=m.group(3).strip(),
        source_type=m.group(2),
        details=m.group(4) or "",
    )


# ------------------------------------------------------------------
# Mode selector
# ------------------------------------------------------------------

def _render_mode_selector() -> None:
    mode = st.selectbox(
        "Query mode",
        options=MODES,
        index=MODES.index(get_mode()),
        key="mode_selector",
    )
    if mode:
        set_mode(mode)
        st.caption(MODE_DESCRIPTIONS[mode])


# ------------------------------------------------------------------
# Controls
# ------------------------------------------------------------------

def _render_controls() -> None:
    if st.button("New conversation", key="new_conv_btn", use_container_width=True):
        clear_messages()
        set_followups([])
        set_error(None)
        st.rerun()


# ------------------------------------------------------------------
# Public helper
# ------------------------------------------------------------------

def refresh_sources_if_needed() -> None:
    """Called on app init to populate sources from server."""
    client = get_client()
    if client and client.connected and not get_sources():
        _refresh_sources(client)
