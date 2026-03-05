"""Sidebar component — source selector, mode picker, conversation controls."""

from __future__ import annotations

import json
import logging

import streamlit as st

from mcpdb.streamlit.mcp_client import McpClientError
from mcpdb.streamlit.state import (
    SourceInfo,
    clear_messages,
    get_active_source,
    get_client,
    get_followups,
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


def render_sidebar() -> None:
    """Render the full sidebar."""
    with st.sidebar:
        st.title("MCPDB")
        st.caption("Natural language database exploration")

        _render_source_section()
        st.divider()
        _render_mode_selector()
        st.divider()
        _render_followups()
        st.divider()
        _render_conversation_controls()


def _render_source_section() -> None:
    """Show connected sources and connection controls."""
    st.subheader("Sources")

    client = get_client()
    sources = get_sources()

    if sources:
        for src in sources:
            active = get_active_source() == src.source_id
            icon = {"database": ":material/database:", "csv": ":material/description:", "excel": ":material/table:"}.get(src.source_type, ":material/source:")
            label = f"{src.name}" + (" *" if active else "")
            st.markdown(f"{icon} **{label}** ({src.source_type})")
    else:
        st.info("No sources connected.")

    # Connect database form
    with st.expander("Connect database", expanded=not sources):
        conn_str = st.text_input(
            "Connection string",
            placeholder="mysql://user:pass@host/db",
            key="connect_db_input",
        )
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Name (optional)", key="connect_db_name")
        with col2:
            if st.button("Connect", key="connect_db_btn", disabled=not conn_str):
                if client and conn_str:
                    _do_connect(client, conn_str, name or None)


def _do_connect(client, conn_str: str, name: str | None) -> None:
    """Execute database connection via MCP."""
    try:
        with st.spinner("Connecting..."):
            result = client.connect_database(conn_str, name=name)
        if result.is_error:
            set_error(result.text)
            st.error(result.text)
        else:
            st.success("Connected!")
            _refresh_sources(client)
    except McpClientError as exc:
        set_error(str(exc))
        st.error(str(exc))


def _refresh_sources(client) -> None:
    """Fetch source list from server and update state."""
    try:
        result = client.list_sources()
        if result.is_error:
            return
        data = result.json
        if data and isinstance(data, list):
            sources = []
            for item in data:
                sources.append(SourceInfo(
                    source_id=item.get("source_id", item.get("id", "")),
                    name=item.get("name", ""),
                    source_type=item.get("type", "database"),
                    details=item.get("details", ""),
                ))
            set_sources(sources)
            if sources and not get_active_source():
                set_active_source(sources[0].source_id)
    except McpClientError:
        logger.warning("Failed to refresh sources", exc_info=True)


def _render_mode_selector() -> None:
    """Mode dropdown."""
    st.subheader("Query Mode")
    mode = st.selectbox(
        "Mode",
        options=MODES,
        index=MODES.index(get_mode()),
        key="mode_selector",
        label_visibility="collapsed",
    )
    if mode:
        set_mode(mode)

    st.caption({
        "auto": "Automatically selects the best mode",
        "quick": "Fast answer from schema context",
        "simple": "Single-pass analysis",
        "optimization": "With validation & replanning",
        "extended": "Multi-revision deep analysis",
        "deep": "Multi-investigation blueprint",
    }.get(mode, ""))


def _render_followups() -> None:
    """Show follow-up suggestions as clickable buttons."""
    followups = get_followups()
    if not followups:
        return

    st.subheader("Follow-ups")
    for i, q in enumerate(followups):
        if st.button(q, key=f"followup_{i}", use_container_width=True):
            # Set the followup as the next question — handled by chat component
            st.session_state["pending_followup"] = q
            st.rerun()


def _render_conversation_controls() -> None:
    """New conversation button."""
    if st.button("New conversation", key="new_conv_btn", use_container_width=True):
        clear_messages()
        set_followups([])
        set_error(None)
        st.rerun()


def refresh_sources_if_needed() -> None:
    """Called on app init to populate sources from server."""
    client = get_client()
    if client and client.connected and not get_sources():
        _refresh_sources(client)
