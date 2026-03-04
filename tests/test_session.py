"""Tests for v1.5.x — Session lifecycle and conversation history."""

from __future__ import annotations

import sqlite3
import time

import pytest

from mcpdb.session import Session, SessionManager
from mcpdb.conversation import ConversationHistory, ConversationMessage
from mcpdb.sources.registry import SourceRegistry
from mcpdb.sources.database.source import DatabaseSource
from mcpdb.mcp.tools.session import get_session_tools, handle_session_tool


@pytest.fixture
def test_db(tmp_path) -> str:
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    c.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    c.executemany("INSERT INTO users VALUES (?, ?)", [(1, "Alice"), (2, "Bob")])
    conn.commit()
    conn.close()
    return f"sqlite:///{db_path}"


# --- Session lifecycle tests (v1.5.0) ---


class TestSession:
    def test_session_creation(self):
        s = Session(
            session_id="test",
            created_at=time.time(),
            last_activity=time.time(),
        )
        assert s.session_id == "test"
        assert not s.is_expired
        assert s.age_seconds >= 0
        assert s.idle_seconds >= 0

    def test_session_touch(self):
        s = Session(
            session_id="test",
            created_at=time.time() - 100,
            last_activity=time.time() - 100,
        )
        assert s.idle_seconds >= 99
        s.touch()
        assert s.idle_seconds < 1

    def test_session_expiry(self):
        s = Session(
            session_id="test",
            created_at=time.time() - 200,
            last_activity=time.time() - 200,
            ttl=100,
        )
        assert s.is_expired


class TestSessionManager:
    def test_create_session(self):
        mgr = SessionManager()
        session = mgr.create_session()
        assert session.session_id.startswith("s_")
        assert mgr.active_count == 1

    def test_create_with_id(self):
        mgr = SessionManager()
        session = mgr.create_session(session_id="custom")
        assert session.session_id == "custom"

    def test_create_duplicate_raises(self):
        mgr = SessionManager()
        mgr.create_session(session_id="dup")
        with pytest.raises(ValueError, match="already exists"):
            mgr.create_session(session_id="dup")

    def test_max_sessions(self):
        mgr = SessionManager(max_sessions=2)
        mgr.create_session(session_id="s1")
        mgr.create_session(session_id="s2")
        with pytest.raises(ValueError, match="Maximum sessions"):
            mgr.create_session(session_id="s3")

    def test_get_session(self):
        mgr = SessionManager()
        created = mgr.create_session(session_id="test")
        found = mgr.get_session("test")
        assert found is not None
        assert found.session_id == "test"

    def test_get_nonexistent(self):
        mgr = SessionManager()
        assert mgr.get_session("nope") is None

    def test_get_expired(self):
        mgr = SessionManager(default_ttl=1)
        mgr.create_session(session_id="short")
        # Manually expire
        mgr._sessions["short"].last_activity = time.time() - 2
        assert mgr.get_session("short") is None

    def test_get_or_create(self):
        mgr = SessionManager()
        s1 = mgr.get_or_create("test")
        s2 = mgr.get_or_create("test")
        assert s1.session_id == s2.session_id
        assert mgr.active_count == 1

    def test_remove_session(self):
        mgr = SessionManager()
        mgr.create_session(session_id="test")
        assert mgr.remove_session("test") is True
        assert mgr.active_count == 0

    def test_remove_nonexistent(self):
        mgr = SessionManager()
        assert mgr.remove_session("nope") is False

    def test_list_sessions(self):
        mgr = SessionManager()
        mgr.create_session(session_id="s1")
        mgr.create_session(session_id="s2")
        sessions = mgr.list_sessions()
        assert len(sessions) == 2
        ids = {s["session_id"] for s in sessions}
        assert ids == {"s1", "s2"}

    def test_cleanup_expired(self):
        mgr = SessionManager(default_ttl=3600)
        mgr.create_session(session_id="short", ttl=1)
        mgr.create_session(session_id="long", ttl=3600)
        # Manually expire the short session
        mgr._sessions["short"].last_activity = time.time() - 2
        removed = mgr._cleanup_expired()
        assert removed == 1
        assert mgr.active_count == 1

    def test_contains(self):
        mgr = SessionManager()
        mgr.create_session(session_id="test")
        assert "test" in mgr
        assert "nope" not in mgr

    def test_len(self):
        mgr = SessionManager()
        assert len(mgr) == 0
        mgr.create_session()
        assert len(mgr) == 1

    def test_session_metadata(self):
        mgr = SessionManager()
        s = mgr.create_session(metadata={"user": "alice"})
        assert s.metadata["user"] == "alice"

    def test_get_status(self):
        mgr = SessionManager()
        mgr.create_session(session_id="test")
        status = mgr.get_status("test")
        assert status is not None
        assert status["session_id"] == "test"
        assert "age_seconds" in status

    def test_get_status_nonexistent(self):
        mgr = SessionManager()
        assert mgr.get_status("nope") is None


# --- Session status tool tests ---


class TestGetSessionStatusTool:
    def test_get_session_status_empty(self):
        registry = SourceRegistry()
        result = handle_session_tool("get_session_status", {
            "_name": "get_session_status",
        }, registry)
        text = result[0].text
        assert "Session Status" in text
        assert "Active sources: 0" in text

    def test_get_session_status_with_source(self, test_db):
        registry = SourceRegistry()
        source = DatabaseSource(test_db)
        registry.add_source(source)
        result = handle_session_tool("get_session_status", {
            "_name": "get_session_status",
        }, registry)
        text = result[0].text
        assert "Active sources: 1" in text
        assert "database" in text
        assert "sql" in text  # capability
        registry.close_all()

    def test_session_tools_count(self):
        tools = get_session_tools()
        assert len(tools) == 6  # connect, list, remove, get_schema, get_session_status, load_csv_files


# --- Conversation history tests (v1.5.1) ---


class TestConversationMessage:
    def test_creation(self):
        msg = ConversationMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.timestamp > 0

    def test_to_dict(self):
        msg = ConversationMessage(role="user", content="Hi", metadata={"key": "val"})
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "Hi"
        assert d["metadata"]["key"] == "val"


class TestConversationHistory:
    def test_add_message(self):
        h = ConversationHistory()
        h.add_message("user", "Hello")
        assert h.message_count == 1
        assert h.total_messages == 1

    def test_multiple_messages(self):
        h = ConversationHistory()
        h.add_message("user", "Hello")
        h.add_message("assistant", "Hi there")
        assert h.message_count == 2

    def test_no_summarization_needed(self):
        h = ConversationHistory(window_size=50)
        for i in range(10):
            h.add_message("user", f"Message {i}")
        assert not h.needs_summarization

    def test_summarization_needed(self):
        h = ConversationHistory(window_size=5, summary_batch=3)
        for i in range(10):
            h.add_message("user", f"Message {i}")
        assert h.needs_summarization

    def test_compact_no_overflow(self):
        h = ConversationHistory(window_size=50)
        h.add_message("user", "Hello")
        summary = h.compact()
        assert summary is None

    def test_compact_with_overflow(self):
        h = ConversationHistory(window_size=5)
        for i in range(10):
            h.add_message("user", f"Message {i}")

        summary = h.compact()
        assert summary is not None
        assert summary.message_count == 5
        assert h.message_count == 5
        assert h.summary_count == 1

    def test_compact_with_llm_summary(self):
        h = ConversationHistory(window_size=3)
        for i in range(6):
            h.add_message("user", f"Question {i}")

        summary = h.compact(llm_summary="User asked 3 questions about data.")
        assert summary is not None
        assert "User asked 3 questions" in summary.text

    def test_compact_fallback_concatenation(self):
        h = ConversationHistory(window_size=3)
        for i in range(6):
            h.add_message("user", f"Q{i}")

        summary = h.compact()  # No LLM summary
        assert summary is not None
        assert "[USER]" in summary.text

    def test_messages_for_prompt(self):
        h = ConversationHistory(window_size=3)
        for i in range(6):
            h.add_message("user", f"Q{i}")

        h.compact(llm_summary="Summary of earlier messages")
        messages = h.get_messages_for_prompt()

        # First message should be summary context
        assert messages[0]["role"] == "system"
        assert "Summary" in messages[0]["content"]
        # Remaining should be recent messages
        assert len(messages) == 4  # 1 summary + 3 recent

    def test_messages_for_prompt_no_summary(self):
        h = ConversationHistory()
        h.add_message("user", "Hello")
        h.add_message("assistant", "Hi")

        messages = h.get_messages_for_prompt()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"

    def test_context_string(self):
        h = ConversationHistory(window_size=3)
        for i in range(6):
            h.add_message("user", f"Q{i}")

        h.compact()
        ctx = h.get_context_string()
        assert "Summary" in ctx
        assert "Recent Messages" in ctx

    def test_context_string_empty(self):
        h = ConversationHistory()
        assert "No conversation" in h.get_context_string()

    def test_get_messages_for_summarization(self):
        h = ConversationHistory(window_size=5)
        for i in range(8):
            h.add_message("user", f"M{i}")

        overflow = h.get_messages_for_summarization()
        assert len(overflow) == 3

    def test_clear(self):
        h = ConversationHistory()
        h.add_message("user", "Hello")
        h.clear()
        assert h.message_count == 0
        assert h.total_messages == 0

    def test_to_dict(self):
        h = ConversationHistory(window_size=10)
        for i in range(5):
            h.add_message("user", f"M{i}")
        d = h.to_dict()
        assert d["message_count"] == 5
        assert d["window_size"] == 10

    def test_multiple_compactions(self):
        h = ConversationHistory(window_size=3)
        # First batch
        for i in range(6):
            h.add_message("user", f"Batch1-{i}")
        h.compact(llm_summary="First batch summary")

        # Second batch
        for i in range(6):
            h.add_message("user", f"Batch2-{i}")
        h.compact(llm_summary="Second batch summary")

        assert h.summary_count == 2
        messages = h.get_messages_for_prompt()
        # Should have summary context (with both summaries) + recent messages
        assert "First batch" in messages[0]["content"]
        assert "Second batch" in messages[0]["content"]

    def test_long_message_truncation_in_fallback(self):
        h = ConversationHistory(window_size=2)
        h.add_message("user", "x" * 500)
        h.add_message("user", "short")
        h.add_message("user", "recent1")
        h.add_message("user", "recent2")

        summary = h.compact()  # Fallback truncation
        assert "..." in summary.text  # Long message was truncated

    def test_metadata_preserved(self):
        h = ConversationHistory()
        h.add_message("user", "Hello", metadata={"tool": "ask_question"})
        messages = h.get_messages_for_prompt()
        # Metadata not included in prompt messages (only content/role)
        assert "tool" not in messages[0]
