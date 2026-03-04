"""Tests for v3.7.x — Progressive Tool Disclosure."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mcpdb.mcp.tool_visibility import (
    DEFAULT_TIERS,
    ToolTier,
    ToolUsageStats,
    ToolVisibilityManager,
)


def _mock_tool(name: str) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    return tool


# ---------------------------------------------------------------------------
# ToolTier constants
# ---------------------------------------------------------------------------

class TestToolTier:
    def test_tier_ordering(self):
        assert ToolTier.ALWAYS < ToolTier.CONNECTED
        assert ToolTier.CONNECTED < ToolTier.QUERYING
        assert ToolTier.QUERYING < ToolTier.ADVANCED
        assert ToolTier.ADVANCED < ToolTier.EXPERT

    def test_default_tiers_populated(self):
        assert len(DEFAULT_TIERS) > 0
        assert DEFAULT_TIERS["connect_database"] == ToolTier.ALWAYS
        assert DEFAULT_TIERS["execute_sql"] == ToolTier.CONNECTED


# ---------------------------------------------------------------------------
# ToolUsageStats
# ---------------------------------------------------------------------------

class TestToolUsageStats:
    def test_record_call(self):
        stats = ToolUsageStats()
        stats.record_call("execute_sql")
        assert stats.calls["execute_sql"] == 1

    def test_record_error(self):
        stats = ToolUsageStats()
        stats.record_call("execute_sql", success=False)
        assert stats.errors["execute_sql"] == 1

    def test_most_used(self):
        stats = ToolUsageStats()
        stats.record_call("a")
        stats.record_call("a")
        stats.record_call("b")
        top = stats.get_most_used(2)
        assert top[0] == ("a", 2)
        assert top[1] == ("b", 1)

    def test_total_calls(self):
        stats = ToolUsageStats()
        stats.record_call("a")
        stats.record_call("b")
        stats.record_call("c")
        assert stats.get_total_calls() == 3

    def test_error_rate(self):
        stats = ToolUsageStats()
        stats.record_call("x", success=True)
        stats.record_call("x", success=False)
        assert stats.get_error_rate("x") == 0.5

    def test_error_rate_no_calls(self):
        stats = ToolUsageStats()
        assert stats.get_error_rate("x") == 0.0


# ---------------------------------------------------------------------------
# ToolVisibilityManager
# ---------------------------------------------------------------------------

class TestVisibilityManager:
    def test_initial_tier(self):
        mgr = ToolVisibilityManager()
        assert mgr.current_tier == ToolTier.ALWAYS

    def test_source_connected_upgrades(self):
        mgr = ToolVisibilityManager()
        mgr.on_source_connected()
        assert mgr.current_tier == ToolTier.CONNECTED

    def test_query_upgrades(self):
        mgr = ToolVisibilityManager()
        mgr.on_source_connected()
        mgr.on_query_executed()
        assert mgr.current_tier == ToolTier.QUERYING

    def test_advanced_after_threshold(self):
        mgr = ToolVisibilityManager()
        mgr.on_source_connected()
        for _ in range(5):
            mgr.on_query_executed()
        assert mgr.current_tier == ToolTier.ADVANCED

    def test_disconnect_downgrades(self):
        mgr = ToolVisibilityManager()
        mgr.on_source_connected()
        assert mgr.current_tier == ToolTier.CONNECTED
        mgr.on_source_disconnected(sources_remaining=0)
        assert mgr.current_tier == ToolTier.ALWAYS

    def test_disconnect_with_remaining(self):
        mgr = ToolVisibilityManager()
        mgr.on_source_connected()
        mgr.on_source_disconnected(sources_remaining=1)
        assert mgr.current_tier == ToolTier.CONNECTED

    def test_filter_tools_initial(self):
        mgr = ToolVisibilityManager()
        tools = [
            _mock_tool("connect_database"),  # ALWAYS
            _mock_tool("execute_sql"),        # CONNECTED
            _mock_tool("explain_query"),      # QUERYING
        ]
        visible = mgr.filter_tools(tools)
        names = [t.name for t in visible]
        assert "connect_database" in names
        assert "execute_sql" not in names
        assert "explain_query" not in names

    def test_filter_tools_connected(self):
        mgr = ToolVisibilityManager()
        mgr.on_source_connected()
        tools = [
            _mock_tool("connect_database"),
            _mock_tool("execute_sql"),
            _mock_tool("explain_query"),
        ]
        visible = mgr.filter_tools(tools)
        names = [t.name for t in visible]
        assert "connect_database" in names
        assert "execute_sql" in names
        assert "explain_query" not in names

    def test_filter_tools_querying(self):
        mgr = ToolVisibilityManager()
        mgr.on_source_connected()
        mgr.on_query_executed()
        tools = [
            _mock_tool("connect_database"),
            _mock_tool("execute_sql"),
            _mock_tool("explain_query"),
        ]
        visible = mgr.filter_tools(tools)
        assert len(visible) == 3

    def test_explicit_unlock(self):
        mgr = ToolVisibilityManager()
        mgr.unlock_tool("get_experience_stats")  # EXPERT tier
        tools = [_mock_tool("get_experience_stats")]
        visible = mgr.filter_tools(tools)
        assert len(visible) == 1

    def test_is_visible(self):
        mgr = ToolVisibilityManager()
        assert mgr.is_visible("connect_database") is True
        assert mgr.is_visible("execute_sql") is False

    def test_is_visible_after_connect(self):
        mgr = ToolVisibilityManager()
        mgr.on_source_connected()
        assert mgr.is_visible("execute_sql") is True

    def test_set_tier(self):
        mgr = ToolVisibilityManager()
        mgr.set_tier("my_custom_tool", ToolTier.ALWAYS)
        tools = [_mock_tool("my_custom_tool")]
        visible = mgr.filter_tools(tools)
        assert len(visible) == 1

    def test_record_usage(self):
        mgr = ToolVisibilityManager()
        mgr.record_usage("execute_sql")
        mgr.record_usage("execute_sql")
        assert mgr.usage_stats.calls["execute_sql"] == 2

    def test_get_state(self):
        mgr = ToolVisibilityManager()
        mgr.on_source_connected()
        state = mgr.get_state()
        assert state["current_tier"] == ToolTier.CONNECTED
        assert state["has_source"] is True
        assert state["query_count"] == 0

    def test_unknown_tool_default_tier(self):
        mgr = ToolVisibilityManager()
        # Unknown tools default to CONNECTED tier
        tools = [_mock_tool("unknown_tool")]
        visible = mgr.filter_tools(tools)
        assert len(visible) == 0  # Not visible at ALWAYS tier

        mgr.on_source_connected()
        visible = mgr.filter_tools(tools)
        assert len(visible) == 1  # Visible at CONNECTED tier
