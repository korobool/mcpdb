"""Chat component — message display, input handling, response rendering."""

from __future__ import annotations

import json
import logging
import time

import streamlit as st

from mcpdb.streamlit.mcp_client import McpClientError, ToolResult
from mcpdb.streamlit.state import (
    ChatMessage,
    add_message,
    get_client,
    get_followups,
    get_messages,
    get_mode,
    get_sources,
    is_busy,
    set_busy,
    set_error,
    set_followups,
)

logger = logging.getLogger(__name__)


def render_chat() -> None:
    """Render the full chat interface."""
    _render_messages()
    _handle_input()


def _render_messages() -> None:
    """Display all messages in the conversation."""
    for msg in get_messages():
        with st.chat_message(msg.role):
            _render_message_content(msg)


def _render_message_content(msg: ChatMessage) -> None:
    """Render a single message's content with rich formatting."""
    content = msg.content

    # Check for metadata with structured data
    mode = msg.metadata.get("mode")
    elapsed = msg.metadata.get("elapsed_seconds")

    st.markdown(content)

    # Show metadata footer for assistant messages
    if msg.role == "assistant" and (mode or elapsed):
        parts = []
        if mode:
            parts.append(f"Mode: {mode}")
        if elapsed:
            parts.append(f"Time: {elapsed:.1f}s")
        st.caption(" | ".join(parts))


def _handle_input() -> None:
    """Handle chat input and followup triggers."""
    # Check for pending followup from sidebar
    pending = st.session_state.get("pending_followup")
    if pending:
        del st.session_state["pending_followup"]
        _submit_question(pending)
        return

    # Chat input
    client = get_client()
    sources = get_sources()

    if not client or not client.connected:
        st.chat_input("Connect to a database first...", disabled=True)
        return

    if not sources:
        st.chat_input("No sources available. Connect a database in the sidebar.", disabled=True)
        return

    question = st.chat_input("Ask a question about your data...")
    if question:
        _submit_question(question)


def _submit_question(question: str) -> None:
    """Submit a question to the MCP server and display the response."""
    client = get_client()
    if not client or not client.connected:
        st.error("Not connected to server.")
        return

    # Add user message
    add_message("user", question)

    # Display user message immediately
    with st.chat_message("user"):
        st.markdown(question)

    # Get response
    with st.chat_message("assistant"):
        with st.status("Analyzing...", expanded=True) as status:
            set_busy(True)
            set_error(None)

            try:
                start = time.time()
                mode = get_mode()
                result = client.ask(question, mode=mode, timeout=600)
                elapsed = time.time() - start

                if result.is_error:
                    status.update(label="Error", state="error")
                    st.error(result.text)
                    add_message(
                        "assistant",
                        f"Error: {result.text}",
                        is_error=True,
                    )
                else:
                    status.update(label=f"Done ({elapsed:.1f}s)", state="complete")
                    response_text = _extract_response(result)
                    metadata = _extract_metadata(result, elapsed)
                    st.markdown(response_text)

                    # Show metadata
                    if metadata.get("mode") or elapsed:
                        parts = []
                        if metadata.get("mode"):
                            parts.append(f"Mode: {metadata['mode']}")
                        parts.append(f"Time: {elapsed:.1f}s")
                        st.caption(" | ".join(parts))

                    add_message("assistant", response_text, **metadata)

                    # Fetch follow-up suggestions
                    _fetch_followups(client, question)

            except McpClientError as exc:
                status.update(label="Error", state="error")
                error_msg = str(exc)
                st.error(error_msg)
                set_error(error_msg)
                add_message("assistant", f"Error: {error_msg}", is_error=True)
            finally:
                set_busy(False)


def _extract_response(result: ToolResult) -> str:
    """Extract the response text from a tool result.

    The ask_question tool currently returns a single TextContent block.
    Future versions may return multiple blocks with structured data.
    """
    # Try JSON first — structured response
    data = result.json
    if data and isinstance(data, dict):
        # Structured response with 'response' field
        if "response" in data:
            return data["response"]
        # Fallback — format as readable text
        return result.text

    # Plain text response
    return result.text


def _extract_metadata(result: ToolResult, elapsed: float) -> dict:
    """Extract metadata from the tool result."""
    meta: dict = {"elapsed_seconds": elapsed}
    data = result.json
    if data and isinstance(data, dict):
        if "mode" in data:
            meta["mode"] = data["mode"]
        if "steps" in data:
            meta["steps"] = data["steps"]
    return meta


def _fetch_followups(client, question: str) -> None:
    """Fetch follow-up suggestions (best-effort, non-blocking to UX)."""
    try:
        result = client.suggest_followups(question)
        if not result.is_error:
            data = result.json
            if data and isinstance(data, list):
                set_followups(data[:5])
            elif isinstance(data, dict) and "suggestions" in data:
                set_followups(data["suggestions"][:5])
            else:
                # Try parsing text as newline-separated suggestions
                lines = [
                    line.strip().lstrip("- ").lstrip("* ")
                    for line in result.text.strip().splitlines()
                    if line.strip() and not line.strip().startswith("#")
                ]
                set_followups(lines[:5])
    except McpClientError:
        logger.debug("Failed to fetch followups", exc_info=True)
