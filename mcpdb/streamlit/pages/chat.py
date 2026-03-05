"""Main chat page."""

from __future__ import annotations

import streamlit as st

from mcpdb.streamlit.components.chat import render_chat
from mcpdb.streamlit.components.sidebar import render_sidebar, refresh_sources_if_needed


def render() -> None:
    """Render the chat page."""
    refresh_sources_if_needed()
    render_sidebar()
    render_chat()
