"""MCP client that spawns and communicates with the MCPDB server.

Manages the server as a subprocess via stdio transport. Provides synchronous
wrappers around the async MCP SDK for use in Streamlit's sync execution model.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
from datetime import timedelta
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

logger = logging.getLogger(__name__)

# Timeout for long-running tool calls like ask_question (deep mode can take 10+ min)
_TOOL_TIMEOUT = timedelta(seconds=600)
# Timeout for fast operations (list_sources, describe_table, etc.)
_FAST_TIMEOUT = timedelta(seconds=30)


class McpClientError(Exception):
    """Raised when an MCP operation fails."""


class ProgressLog:
    """Thread-safe collector for MCP log notifications."""

    def __init__(self) -> None:
        self._messages: list[str] = []
        self._lock = threading.Lock()

    def append(self, message: str) -> None:
        with self._lock:
            self._messages.append(message)

    def drain(self) -> list[str]:
        """Return and clear all collected messages."""
        with self._lock:
            msgs = list(self._messages)
            self._messages.clear()
            return msgs

    def clear(self) -> None:
        with self._lock:
            self._messages.clear()


class McpdbClient:
    """MCP client that spawns MCPDB server and provides sync wrappers.

    Uses a dedicated asyncio event loop running in a background thread.
    The MCP session and server subprocess persist across Streamlit reruns
    via ``@st.cache_resource``.
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="mcp-client-loop"
        )
        self._thread.start()

        self._session: ClientSession | None = None
        self._stdio_cm: Any = None  # context manager from stdio_client
        self._session_cm: Any = None  # context manager from ClientSession
        self._connected = False
        self._server_env: dict[str, str] = {}
        self.progress = ProgressLog()

    def _run_loop(self) -> None:
        """Run the dedicated event loop in background thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    @property
    def connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self, db_url: str | None = None, timeout: float = 30) -> None:
        """Spawn MCPDB server subprocess and establish MCP session.

        Args:
            db_url: Database URL to set as MCPDB_DATABASE_URL env var for server.
            timeout: Connection timeout in seconds.
        """
        future = asyncio.run_coroutine_threadsafe(
            self._connect(db_url=db_url), self._loop
        )
        try:
            future.result(timeout=timeout)
        except Exception as exc:
            raise McpClientError(f"Failed to connect: {exc}") from exc

    async def _connect(self, db_url: str | None = None) -> None:
        # Build environment for server subprocess
        env = _build_server_env(db_url)
        self._server_env = env

        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcpdb", "serve"],
            env=env,
        )

        # Enter stdio_client context manager (spawns subprocess)
        self._stdio_cm = stdio_client(server_params)
        read_stream, write_stream = await self._stdio_cm.__aenter__()

        # Enter ClientSession context manager (with logging callback for progress)
        progress_ref = self.progress

        async def _on_log(params) -> None:
            """Receive MCP log notifications from the server."""
            data = params.data if hasattr(params, "data") else str(params)
            if isinstance(data, str):
                progress_ref.append(data)
            else:
                progress_ref.append(str(data))

        self._session_cm = ClientSession(
            read_stream, write_stream,
            logging_callback=_on_log,
        )
        self._session = await self._session_cm.__aenter__()

        # Initialize the MCP protocol handshake
        result = await self._session.initialize()
        logger.info("MCP session initialized: %s", result)
        self._connected = True

    def close(self) -> None:
        """Shut down MCP session and server subprocess."""
        if not self._connected:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(self._close(), self._loop)
            future.result(timeout=10)
        except Exception:
            logger.warning("Error during MCP client shutdown", exc_info=True)
        finally:
            self._connected = False
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)

    async def _close(self) -> None:
        if self._session_cm:
            try:
                await self._session_cm.__aexit__(None, None, None)
            except Exception:
                pass
        if self._stdio_cm:
            try:
                await self._stdio_cm.__aexit__(None, None, None)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Sync wrappers for MCP operations
    # ------------------------------------------------------------------

    def _run(self, coro: Any, timeout: float = 30) -> Any:
        """Run an async coroutine from sync Streamlit code."""
        if not self._connected or not self._session:
            raise McpClientError("Not connected. Call connect() first.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except asyncio.TimeoutError:
            raise McpClientError(f"Operation timed out after {timeout}s")
        except Exception as exc:
            raise McpClientError(str(exc)) from exc

    def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None, timeout: float = 600
    ) -> ToolResult:
        """Call an MCP tool and return parsed result."""
        assert self._session is not None
        raw = self._run(
            self._session.call_tool(
                name,
                arguments or {},
                read_timeout_seconds=_TOOL_TIMEOUT,
            ),
            timeout=timeout,
        )
        return ToolResult.from_raw(raw)

    def read_resource(self, uri: str, timeout: float = 30) -> str:
        """Read an MCP resource and return its text content."""
        assert self._session is not None
        raw = self._run(
            self._session.read_resource(uri),
            timeout=timeout,
        )
        # ReadResourceResult has .contents list
        parts = []
        for content in raw.contents:
            if hasattr(content, "text"):
                parts.append(content.text)
        return "\n".join(parts)

    def list_tools(self, timeout: float = 10) -> list[dict[str, Any]]:
        """List available MCP tools."""
        assert self._session is not None
        raw = self._run(self._session.list_tools(), timeout=timeout)
        return [
            {"name": t.name, "description": t.description or ""}
            for t in raw.tools
        ]

    def list_resources(self, timeout: float = 10) -> list[dict[str, Any]]:
        """List available MCP resources."""
        assert self._session is not None
        raw = self._run(self._session.list_resources(), timeout=timeout)
        return [
            {"name": r.name, "uri": str(r.uri), "description": r.description or ""}
            for r in raw.resources
        ]

    # ------------------------------------------------------------------
    # High-level convenience methods
    # ------------------------------------------------------------------

    def ask(self, question: str, mode: str = "auto", timeout: float = 600) -> ToolResult:
        """Ask a question via the ask_question tool."""
        args: dict[str, Any] = {"question": question}
        if mode != "auto":
            args["mode"] = mode
        return self.call_tool("ask_question", args, timeout=timeout)

    def ask_async(
        self, question: str, mode: str = "auto", timeout: float = 600,
    ) -> threading.Event:
        """Start ask_question in background; poll ``progress`` for updates.

        Returns a ``threading.Event`` that is set when the call completes.
        The result is stored in ``self._ask_result`` / ``self._ask_error``.
        """
        self.progress.clear()
        self._ask_result: ToolResult | None = None
        self._ask_error: Exception | None = None
        done_event = threading.Event()

        def _run() -> None:
            try:
                self._ask_result = self.ask(question, mode=mode, timeout=timeout)
            except Exception as exc:
                self._ask_error = exc
            finally:
                done_event.set()

        t = threading.Thread(target=_run, daemon=True, name="ask-question")
        t.start()
        return done_event

    def list_sources(self) -> ToolResult:
        return self.call_tool("list_sources", timeout=30)

    def connect_database(self, connection_string: str, name: str | None = None) -> ToolResult:
        args: dict[str, Any] = {"connection_string": connection_string}
        if name:
            args["name"] = name
        return self.call_tool("connect_database", args, timeout=30)

    def get_schema(self, source_id: str) -> str:
        """Read schema resource for a source."""
        return self.read_resource(f"schema://{source_id}")

    def get_erd(self, source_id: str) -> str:
        """Read ERD resource for a source."""
        return self.read_resource(f"erd://{source_id}")

    def describe_table(self, table_name: str, source_id: str | None = None) -> ToolResult:
        args: dict[str, Any] = {"table_name": table_name}
        if source_id:
            args["source_id"] = source_id
        return self.call_tool("describe_table", args, timeout=30)

    def suggest_followups(self, context: str | None = None) -> ToolResult:
        args: dict[str, Any] = {}
        if context:
            args["context"] = context
        return self.call_tool("suggest_followups", args, timeout=30)

    def run_query(self, query: str, source_id: str | None = None) -> ToolResult:
        args: dict[str, Any] = {"query": query}
        if source_id:
            args["source_id"] = source_id
        return self.call_tool("run_query", args, timeout=60)

    def load_csv_files(self, paths: list[str]) -> ToolResult:
        return self.call_tool("load_csv_files", {"paths": paths}, timeout=60)

    def remove_source(self, source_id: str) -> ToolResult:
        return self.call_tool("remove_source", {"source_id": source_id}, timeout=10)


class ToolResult:
    """Parsed result from an MCP tool call."""

    def __init__(
        self, text: str, is_error: bool = False, raw_content: list[Any] | None = None
    ) -> None:
        self.text = text
        self.is_error = is_error
        self.raw_content = raw_content or []

    @classmethod
    def from_raw(cls, raw: Any) -> ToolResult:
        """Parse a CallToolResult from the MCP SDK."""
        texts = []
        for block in raw.content:
            if hasattr(block, "text"):
                texts.append(block.text)
        return cls(
            text="\n".join(texts),
            is_error=getattr(raw, "isError", False),
            raw_content=list(raw.content),
        )

    @property
    def json(self) -> dict[str, Any] | None:
        """Try to parse the text as JSON."""
        try:
            return json.loads(self.text)
        except (json.JSONDecodeError, TypeError):
            return None

    def __repr__(self) -> str:
        preview = self.text[:80] + "..." if len(self.text) > 80 else self.text
        return f"ToolResult(is_error={self.is_error}, text={preview!r})"


def _build_server_env(db_url: str | None = None) -> dict[str, str]:
    """Build environment variables for the server subprocess.

    Passes through relevant env vars (API keys, database URL, PATH, etc.)
    """
    # Start with minimal safe environment
    env: dict[str, str] = {}

    # Pass through essential system vars
    for key in ("PATH", "HOME", "USER", "LANG", "TERM", "VIRTUAL_ENV",
                "PYTHONPATH", "LD_LIBRARY_PATH"):
        val = os.environ.get(key)
        if val:
            env[key] = val

    # Pass through API keys
    for key in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                "GOOGLE_API_KEY"):
        val = os.environ.get(key)
        if val:
            env[key] = val

    # Database URL — explicit arg takes priority over env var
    if db_url:
        env["MCPDB_DATABASE_URL"] = db_url
    elif os.environ.get("MCPDB_DATABASE_URL"):
        env["MCPDB_DATABASE_URL"] = os.environ["MCPDB_DATABASE_URL"]

    # Pass through MCPDB config path if set
    config_path = os.environ.get("MCPDB_CONFIG")
    if config_path:
        env["MCPDB_CONFIG"] = config_path

    return env
