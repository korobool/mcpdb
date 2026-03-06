"""Chat component — message display, input handling, response rendering."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import streamlit as st

from mcpdb.streamlit.mcp_client import McpClientError, ToolResult
from mcpdb.streamlit.state import (
    ChatMessage,
    add_message,
    get_client,
    get_messages,
    get_mode,
    get_sources,
    set_busy,
    set_error,
)

logger = logging.getLogger(__name__)

_MERMAID_KEYWORDS = (
    "erDiagram", "graph ", "graph\n", "flowchart ", "sequenceDiagram",
    "classDiagram", "stateDiagram", "gantt", "pie ", "pie\n",
    "gitGraph", "journey", "mindmap", "timeline",
)


# =====================================================================
# Top-level entry point
# =====================================================================

def render_chat() -> None:
    """Render the full chat interface (single-column, full-width)."""
    sources = get_sources()
    client = get_client()

    if not client or not client.connected:
        _render_placeholder("Starting MCP server...")
        return

    if not sources:
        _render_placeholder(
            "No data sources connected yet.\n\n"
            "Use the sidebar to connect a database, CSV, or Excel file."
        )
        st.chat_input("Connect a data source first...", disabled=True)
        return

    if not get_messages():
        _ensure_welcome_data(client, sources)

    _render_messages()
    _handle_input()


# =====================================================================
# Welcome / onboarding
# =====================================================================

def _render_placeholder(message: str) -> None:
    """Centered status message when not yet connected."""
    st.markdown(
        f"<div class='mcpdb-welcome'>"
        f"<h2>MCPDB</h2><p>{message}</p></div>",
        unsafe_allow_html=True,
    )


def _ensure_welcome_data(client, sources: list) -> None:
    """Fetch schema summary, ERD, and starter questions once per source set."""
    source_key = ",".join(s.source_id for s in sources)
    if st.session_state.get("_welcome_source_key") == source_key:
        return

    st.session_state["_welcome_source_key"] = source_key

    src = sources[0]

    # Schema summary via schema:// resource (JSON with table list)
    try:
        schema_text = client.get_schema(src.source_id)
        schema_data = json.loads(schema_text)
        st.session_state["_welcome_schema"] = {
            "source_name": schema_data.get("display_name", src.name),
            "source_type": schema_data.get("source_type", src.source_type),
            "tables": [
                {
                    "name": t["name"],
                    "columns": len(t.get("columns", [])),
                    "rows": t.get("row_count"),
                }
                for t in schema_data.get("tables", [])
            ],
        }
    except (McpClientError, json.JSONDecodeError, KeyError):
        logger.debug("Failed to fetch schema summary", exc_info=True)

    # ERD mermaid diagram
    try:
        result = client.call_tool(
            "render_erd", {"source_id": src.source_id}, timeout=30,
        )
        if not result.is_error and result.text.strip():
            st.session_state["_welcome_erd"] = result.text.strip()
    except McpClientError:
        logger.debug("Failed to fetch ERD", exc_info=True)

    # Starter questions
    try:
        result = client.suggest_followups()
        if not result.is_error:
            data = result.json
            if isinstance(data, list):
                st.session_state["_welcome_followups"] = data[:6]
            elif isinstance(data, dict) and "suggestions" in data:
                st.session_state["_welcome_followups"] = data["suggestions"][:6]
            else:
                lines = [
                    line.strip().lstrip("0123456789. ").lstrip("- ").lstrip("* ")
                    for line in result.text.strip().splitlines()
                    if line.strip() and not line.strip().startswith("#")
                ]
                if lines:
                    st.session_state["_welcome_followups"] = lines[:6]
    except McpClientError:
        logger.debug("Failed to fetch followups", exc_info=True)


def _render_welcome_with_context() -> None:
    """Welcome screen: schema overview, ERD expander, starter questions."""
    schema = st.session_state.get("_welcome_schema")
    erd = st.session_state.get("_welcome_erd")
    followups = st.session_state.get("_welcome_followups")

    if schema:
        table_count = len(schema["tables"])
        st.markdown(
            f"### Connected to **{schema['source_name']}**\n"
            f"{table_count} table{'s' if table_count != 1 else ''} available"
        )
        if schema["tables"]:
            _render_schema_overview(schema["tables"])
    else:
        st.markdown("### Ready to explore your data")

    if erd:
        st.markdown("#### Schema diagram")
        _render_mermaid(erd)

    if followups:
        st.markdown("**Try asking:**")
        _render_followups(followups, key_prefix="welcome")


def _render_schema_overview(tables: list[dict]) -> None:
    """Compact table list with column counts and row counts."""
    import pandas as pd

    df = pd.DataFrame(tables)
    df.columns = ["Table", "Columns", "Rows"]
    df["Rows"] = df["Rows"].apply(lambda x: f"{x:,}" if x is not None else "\u2014")
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=min(35 * len(tables) + 38, 400),
    )


# =====================================================================
# Messages
# =====================================================================

def _render_messages() -> None:
    """Display all messages, or welcome screen if empty."""
    messages = get_messages()
    if not messages:
        if "pending_followup" not in st.session_state:
            _render_welcome_with_context()
        return

    for idx, msg in enumerate(messages):
        with st.chat_message(msg.role):
            _render_message_content(msg, msg_idx=idx)


def _render_message_content(msg: ChatMessage, msg_idx: int = 0) -> None:
    """Render a single message with rich text, artifacts, and metadata."""
    _render_rich_text(msg.content)

    if msg.role == "assistant" and not msg.metadata.get("is_error"):
        # Inline artifacts
        for artifact in msg.metadata.get("artifacts", []):
            _render_artifact(artifact)

        # Metadata footer
        parts = []
        if msg.metadata.get("mode"):
            parts.append(f"Mode: {msg.metadata['mode']}")
        if msg.metadata.get("elapsed_seconds"):
            parts.append(f"Time: {msg.metadata['elapsed_seconds']:.1f}s")
        if parts:
            st.caption(" | ".join(parts))

        # Execution log
        log = msg.metadata.get("execution_log", [])
        if log:
            _render_execution_log(log)

        # Follow-up suggestions
        followups = msg.metadata.get("followups")
        if followups:
            _render_followups(followups, key_prefix=f"msg{msg_idx}")


def _render_artifact(artifact: dict[str, Any]) -> None:
    """Render a table or chart artifact inline."""
    a_type = artifact.get("type", "unknown")
    title = artifact.get("title", "")
    data = artifact.get("data", {})

    if a_type == "table":
        if title:
            st.markdown(f"**{title}**")
        columns = data.get("columns", [])
        rows = data.get("rows", [])
        if columns and rows:
            import pandas as pd
            df = pd.DataFrame(rows, columns=columns)
            st.dataframe(df, use_container_width=True)
            if data.get("truncated"):
                st.caption("Showing first 200 rows")

    elif a_type == "chart":
        if title:
            st.markdown(f"**{title}**")
        image_b64 = data.get("image_base64") or data.get("image")
        if image_b64:
            import base64
            st.image(base64.b64decode(image_b64))


def _render_execution_log(log: list[dict]) -> None:
    """Collapsible execution log."""
    with st.expander(f"Execution log ({len(log)} steps)", expanded=False):
        for entry in log:
            step = entry.get("step_number", "?")
            action = entry.get("action", "unknown")
            status = entry.get("status", "")
            time_ms = entry.get("time_ms")
            code = entry.get("code", "")

            icon = {
                "success": "\u2705", "error": "\u274c", "skipped": "\u23ed\ufe0f",
            }.get(status, "\u2699\ufe0f")
            timing = f" ({time_ms}ms)" if time_ms is not None else ""
            st.markdown(f"{icon} **{step}**: {action}{timing}")

            if code:
                st.code(
                    code,
                    language="sql" if "SELECT" in code.upper() else "python",
                )


# =====================================================================
# Rich text / mermaid rendering
# =====================================================================

def _render_rich_text(text: str) -> None:
    """Render text with mermaid diagram support."""
    stripped = text.strip()

    if stripped.startswith(_MERMAID_KEYWORDS):
        _render_mermaid(stripped)
        return

    parts = re.split(r"```mermaid\s*\n(.*?)```", stripped, flags=re.DOTALL)
    if len(parts) > 1:
        for i, part in enumerate(parts):
            if i % 2 == 0:
                if part.strip():
                    st.markdown(part)
            else:
                _render_mermaid(part.strip())
        return

    st.markdown(text)


def _render_mermaid(code: str) -> None:
    """Render a mermaid diagram, stripping trailing metadata lines."""
    lines = code.rstrip().splitlines()
    while lines and lines[-1].strip().startswith("_") and lines[-1].strip().endswith("_"):
        lines.pop()
    clean = "\n".join(lines).strip()

    if not clean:
        return

    try:
        from streamlit_mermaid import st_mermaid
        st_mermaid(clean, height="auto")
    except ImportError:
        st.code(clean, language="mermaid")
    except Exception:
        st.code(clean, language="mermaid")


# =====================================================================
# Input handling
# =====================================================================

def _handle_input() -> None:
    """Handle chat input and follow-up triggers."""
    pending = st.session_state.pop("pending_followup", None)
    if pending:
        _submit_question(pending)
        return

    question = st.chat_input("Ask a question about your data...")
    if question:
        _submit_question(question)


def _submit_question(question: str) -> None:
    """Submit a question to the MCP server and stream the response."""
    client = get_client()
    if not client or not client.connected:
        st.error("Not connected to server.")
        return

    add_message("user", question)
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        response_text = None
        metadata: dict = {}
        error_msg = None

        with st.status("Analyzing...", expanded=True) as status:
            set_busy(True)
            set_error(None)

            start = time.time()
            mode = get_mode()
            done_event = client.ask_async(question, mode=mode, timeout=600)

            progress_placeholder = st.empty()
            all_steps: list[str] = []

            while not done_event.wait(timeout=0.3):
                new_msgs = client.progress.drain()
                if new_msgs:
                    all_steps.extend(new_msgs)
                    _render_progress(progress_placeholder, all_steps, start)

            new_msgs = client.progress.drain()
            if new_msgs:
                all_steps.extend(new_msgs)

            elapsed = time.time() - start
            set_busy(False)

            if client._ask_error is not None:
                status.update(label="Error", state="error")
                error_msg = str(client._ask_error)
            elif client._ask_result is not None:
                result = client._ask_result
                if result.is_error:
                    status.update(label="Error", state="error")
                    error_msg = result.text
                else:
                    response_text = _extract_response(result)
                    metadata = _extract_metadata(result, elapsed)
                    if all_steps:
                        _render_progress(progress_placeholder, all_steps, start)
                    status.update(label=f"Done ({elapsed:.1f}s)", state="complete")
            else:
                status.update(label="Error", state="error")
                error_msg = "No result received"

        # Render response outside the status container
        if error_msg:
            st.error(error_msg)
            set_error(error_msg)
            add_message("assistant", f"Error: {error_msg}", is_error=True)
        elif response_text:
            _render_rich_text(response_text)

            for artifact in metadata.get("artifacts", []):
                _render_artifact(artifact)

            footer = []
            if metadata.get("mode"):
                footer.append(f"Mode: {metadata['mode']}")
            if metadata.get("elapsed_seconds"):
                footer.append(f"Time: {metadata['elapsed_seconds']:.1f}s")
            if footer:
                st.caption(" | ".join(footer))

            log = metadata.get("execution_log", [])
            if log:
                _render_execution_log(log)

            add_message("assistant", response_text, **metadata)

            followups = metadata.get("followups")
            if followups:
                _render_followups(followups, key_prefix="current")


def _render_progress(
    placeholder, steps: list[str], start_time: float,
) -> None:
    """Render progress steps inside an st.empty placeholder."""
    elapsed = time.time() - start_time
    lines = [f"- {s}" for s in steps]
    lines.append(f"\n*{elapsed:.0f}s elapsed*")
    placeholder.markdown("\n".join(lines))


# =====================================================================
# Helpers
# =====================================================================

def _extract_response(result: ToolResult) -> str:
    """Extract the response text from a tool result."""
    data = result.json
    if data and isinstance(data, dict) and "response" in data:
        return data["response"]
    return result.text


def _extract_metadata(result: ToolResult, elapsed: float) -> dict:
    """Extract metadata from the tool result."""
    meta: dict = {"elapsed_seconds": elapsed}
    data = result.json
    if data and isinstance(data, dict):
        for key in ("mode", "steps", "artifacts", "execution_log",
                     "followups", "event_summary"):
            if key in data:
                meta[key] = data[key]
    return meta


def _render_followups(followups: list[str], key_prefix: str = "fup") -> None:
    """Render follow-up suggestion buttons."""
    if not followups:
        return
    cols = st.columns(min(len(followups), 3))
    for i, q in enumerate(followups):
        with cols[i % len(cols)]:
            if st.button(q, key=f"{key_prefix}_{i}", use_container_width=True):
                st.session_state["pending_followup"] = q
                st.rerun()
