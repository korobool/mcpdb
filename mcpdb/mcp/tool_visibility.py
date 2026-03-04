"""Progressive tool disclosure — manage tool visibility based on session state."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from mcp.types import Tool

logger = logging.getLogger("mcpdb.mcp.tool_visibility")


class ToolTier:
    """Tool visibility tiers."""

    ALWAYS = 0       # Always visible (connect, list_sources)
    CONNECTED = 1    # Visible when at least one source is connected
    QUERYING = 2     # Visible after first successful query
    ADVANCED = 3     # Visible after multiple queries or explicit unlock
    EXPERT = 4       # Only visible via explicit unlock


# Default tier assignments for tools
DEFAULT_TIERS: dict[str, int] = {
    # Tier 0 — ALWAYS
    "connect_database": ToolTier.ALWAYS,
    "load_csv_files": ToolTier.ALWAYS,
    "load_excel": ToolTier.ALWAYS,
    "list_sources": ToolTier.ALWAYS,
    "remove_source": ToolTier.ALWAYS,

    # Tier 1 — CONNECTED
    "get_source_schema": ToolTier.CONNECTED,
    "search_schema": ToolTier.CONNECTED,
    "execute_sql": ToolTier.CONNECTED,
    "get_table_sample": ToolTier.CONNECTED,
    "validate_sql": ToolTier.CONNECTED,
    "ask_question": ToolTier.CONNECTED,
    "list_sheets": ToolTier.CONNECTED,
    "read_range": ToolTier.CONNECTED,

    # Tier 2 — QUERYING
    "explain_query": ToolTier.QUERYING,
    "render_erd": ToolTier.QUERYING,
    "profile_table": ToolTier.QUERYING,
    "profile_column": ToolTier.QUERYING,
    "find_relationships": ToolTier.QUERYING,
    "suggest_joins": ToolTier.QUERYING,
    "extract_excel_table": ToolTier.QUERYING,
    "explain_formula": ToolTier.QUERYING,
    "suggest_followups": ToolTier.QUERYING,

    # Tier 3 — ADVANCED
    "cancel_execution": ToolTier.ADVANCED,
    "add_context": ToolTier.ADVANCED,
    "submit_strategy": ToolTier.ADVANCED,
    "export_conversation": ToolTier.ADVANCED,
    "cross_source_query": ToolTier.ADVANCED,

    # Tier 4 — EXPERT
    "get_experience_stats": ToolTier.EXPERT,
    "list_cached_queries": ToolTier.EXPERT,
    "invalidate_cache_entry": ToolTier.EXPERT,
    "clear_experience": ToolTier.EXPERT,
    "vote_response": ToolTier.EXPERT,
}


@dataclass
class ToolUsageStats:
    """Track tool usage for analytics."""

    calls: dict[str, int] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)
    last_used: dict[str, float] = field(default_factory=dict)

    def record_call(self, tool_name: str, success: bool = True) -> None:
        self.calls[tool_name] = self.calls.get(tool_name, 0) + 1
        self.last_used[tool_name] = time.time()
        if not success:
            self.errors[tool_name] = self.errors.get(tool_name, 0) + 1

    def get_most_used(self, n: int = 10) -> list[tuple[str, int]]:
        return sorted(self.calls.items(), key=lambda x: x[1], reverse=True)[:n]

    def get_total_calls(self) -> int:
        return sum(self.calls.values())

    def get_error_rate(self, tool_name: str) -> float:
        total = self.calls.get(tool_name, 0)
        if total == 0:
            return 0.0
        return self.errors.get(tool_name, 0) / total


class ToolVisibilityManager:
    """Manage which tools are visible based on session state.

    Implements progressive disclosure: start with basic tools,
    unlock more as the user progresses.
    """

    def __init__(
        self,
        tier_assignments: dict[str, int] | None = None,
    ) -> None:
        self._tiers = tier_assignments or dict(DEFAULT_TIERS)
        self._current_tier = ToolTier.ALWAYS
        self._explicit_unlocks: set[str] = set()
        self._usage = ToolUsageStats()

        # Session state tracking
        self._has_source = False
        self._query_count = 0
        self._advanced_threshold = 5

    def set_tier(self, tool_name: str, tier: int) -> None:
        """Override the tier for a specific tool."""
        self._tiers[tool_name] = tier

    def unlock_tool(self, tool_name: str) -> None:
        """Explicitly unlock a tool regardless of tier."""
        self._explicit_unlocks.add(tool_name)

    def on_source_connected(self) -> None:
        """Called when a source is connected."""
        self._has_source = True
        self._update_tier()

    def on_source_disconnected(self, sources_remaining: int) -> None:
        """Called when a source is disconnected."""
        if sources_remaining == 0:
            self._has_source = False
            self._update_tier()

    def on_query_executed(self) -> None:
        """Called after a successful query."""
        self._query_count += 1
        self._update_tier()

    def _update_tier(self) -> None:
        """Update the current visibility tier based on session state."""
        if self._query_count >= self._advanced_threshold:
            self._current_tier = ToolTier.ADVANCED
        elif self._query_count > 0:
            self._current_tier = ToolTier.QUERYING
        elif self._has_source:
            self._current_tier = ToolTier.CONNECTED
        else:
            self._current_tier = ToolTier.ALWAYS

    def filter_tools(self, tools: list[Tool]) -> list[Tool]:
        """Filter tools based on current visibility tier."""
        visible = []
        for tool in tools:
            tier = self._tiers.get(tool.name, ToolTier.CONNECTED)
            if tool.name in self._explicit_unlocks or tier <= self._current_tier:
                visible.append(tool)
        return visible

    def is_visible(self, tool_name: str) -> bool:
        """Check if a specific tool is currently visible."""
        if tool_name in self._explicit_unlocks:
            return True
        tier = self._tiers.get(tool_name, ToolTier.CONNECTED)
        return tier <= self._current_tier

    def record_usage(self, tool_name: str, success: bool = True) -> None:
        """Record a tool usage event."""
        self._usage.record_call(tool_name, success)

    @property
    def current_tier(self) -> int:
        return self._current_tier

    @property
    def usage_stats(self) -> ToolUsageStats:
        return self._usage

    def get_state(self) -> dict[str, Any]:
        """Get current visibility state for debugging."""
        return {
            "current_tier": self._current_tier,
            "has_source": self._has_source,
            "query_count": self._query_count,
            "explicit_unlocks": sorted(self._explicit_unlocks),
            "total_tool_calls": self._usage.get_total_calls(),
        }
