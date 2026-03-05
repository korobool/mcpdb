"""Session state management for the Streamlit webchat.

Wraps ``st.session_state`` with typed helpers so components don't need
to scatter magic key names throughout the codebase.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import streamlit as st

from mcpdb.streamlit.mcp_client import McpdbClient

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ChatMessage:
    """A single message in the conversation."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceInfo:
    """Lightweight source descriptor (from list_sources response)."""

    source_id: str
    name: str
    source_type: str  # "database", "csv", "excel"
    details: str = ""


# ---------------------------------------------------------------------------
# Session state accessors
# ---------------------------------------------------------------------------


def get_client() -> McpdbClient | None:
    """Return the cached MCP client, or None if not yet created."""
    return st.session_state.get("mcp_client")


def set_client(client: McpdbClient) -> None:
    st.session_state["mcp_client"] = client


def get_messages() -> list[ChatMessage]:
    if "messages" not in st.session_state:
        st.session_state["messages"] = []
    return st.session_state["messages"]


def add_message(role: str, content: str, **metadata: Any) -> ChatMessage:
    msg = ChatMessage(role=role, content=content, metadata=metadata)
    get_messages().append(msg)
    return msg


def clear_messages() -> None:
    st.session_state["messages"] = []


def get_sources() -> list[SourceInfo]:
    return st.session_state.get("sources", [])


def set_sources(sources: list[SourceInfo]) -> None:
    st.session_state["sources"] = sources


def get_active_source() -> str | None:
    """Return the active source_id, or None."""
    return st.session_state.get("active_source")


def set_active_source(source_id: str | None) -> None:
    st.session_state["active_source"] = source_id


def get_mode() -> str:
    return st.session_state.get("query_mode", "auto")


def set_mode(mode: str) -> None:
    st.session_state["query_mode"] = mode


def is_busy() -> bool:
    """True when the client is waiting for a tool response."""
    return st.session_state.get("busy", False)


def set_busy(busy: bool) -> None:
    st.session_state["busy"] = busy


def get_followups() -> list[str]:
    return st.session_state.get("followups", [])


def set_followups(followups: list[str]) -> None:
    st.session_state["followups"] = followups


def get_error() -> str | None:
    return st.session_state.get("last_error")


def set_error(error: str | None) -> None:
    st.session_state["last_error"] = error


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def init_session_state() -> None:
    """Initialize all session state keys with defaults (idempotent)."""
    defaults = {
        "messages": [],
        "sources": [],
        "active_source": None,
        "query_mode": "auto",
        "busy": False,
        "followups": [],
        "last_error": None,
        "initialized": False,
    }
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default
