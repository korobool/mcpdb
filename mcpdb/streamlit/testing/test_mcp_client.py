"""Tests for the MCP client module."""

from __future__ import annotations

import json
import os

from mcpdb.streamlit.mcp_client import McpdbClient, ToolResult, _build_server_env


class TestBuildServerEnv:
    """Tests for _build_server_env helper."""

    def test_passes_through_api_keys(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
        env = _build_server_env()
        assert env["GEMINI_API_KEY"] == "test-gemini-key"
        assert env["OPENAI_API_KEY"] == "test-openai-key"

    def test_explicit_db_url_takes_priority(self, monkeypatch):
        monkeypatch.setenv("MCPDB_DATABASE_URL", "sqlite:///old.db")
        env = _build_server_env(db_url="sqlite:///new.db")
        assert env["MCPDB_DATABASE_URL"] == "sqlite:///new.db"

    def test_env_db_url_used_when_no_explicit(self, monkeypatch):
        monkeypatch.setenv("MCPDB_DATABASE_URL", "sqlite:///env.db")
        env = _build_server_env()
        assert env["MCPDB_DATABASE_URL"] == "sqlite:///env.db"

    def test_no_db_url_when_missing(self, monkeypatch):
        monkeypatch.delenv("MCPDB_DATABASE_URL", raising=False)
        env = _build_server_env()
        assert "MCPDB_DATABASE_URL" not in env

    def test_passes_path(self, monkeypatch):
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        env = _build_server_env()
        assert env["PATH"] == "/usr/bin:/bin"


class TestToolResult:
    """Tests for ToolResult parsing."""

    def test_from_raw_text_content(self):
        class FakeBlock:
            text = "Hello, world!"

        class FakeRaw:
            content = [FakeBlock()]
            isError = False

        result = ToolResult.from_raw(FakeRaw())
        assert result.text == "Hello, world!"
        assert result.is_error is False

    def test_from_raw_error(self):
        class FakeBlock:
            text = "Something went wrong"

        class FakeRaw:
            content = [FakeBlock()]
            isError = True

        result = ToolResult.from_raw(FakeRaw())
        assert result.is_error is True

    def test_json_property_valid(self):
        result = ToolResult(text='{"key": "value"}')
        assert result.json == {"key": "value"}

    def test_json_property_invalid(self):
        result = ToolResult(text="not json")
        assert result.json is None

    def test_json_property_list(self):
        result = ToolResult(text='[{"id": 1}, {"id": 2}]')
        assert result.json == [{"id": 1}, {"id": 2}]

    def test_repr(self):
        result = ToolResult(text="short text", is_error=False)
        r = repr(result)
        assert "ToolResult" in r
        assert "is_error=False" in r

    def test_multiple_content_blocks(self):
        class FakeBlock:
            def __init__(self, text):
                self.text = text

        class FakeRaw:
            content = [FakeBlock("line1"), FakeBlock("line2")]
            isError = False

        result = ToolResult.from_raw(FakeRaw())
        assert result.text == "line1\nline2"


class TestMcpdbClientInit:
    """Tests for client initialization (no actual server)."""

    def test_client_not_connected_initially(self):
        client = McpdbClient()
        assert client.connected is False
        # Clean up the background thread
        client._loop.call_soon_threadsafe(client._loop.stop)
        client._thread.join(timeout=2)

    def test_close_when_not_connected(self):
        client = McpdbClient()
        # Should not raise
        client.close()
