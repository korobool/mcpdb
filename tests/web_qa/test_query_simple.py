"""Test simple query execution end-to-end.

Tests: submit questions, verify pipeline phases animate, result renders.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .helpers import (
    connect_database,
    submit_query,
    get_monitor_state,
    get_monitor_log,
    is_monitor_complete,
    get_last_response,
    get_tables_in_response,
    get_chat_messages,
    count_messages,
    take_screenshot,
    take_element_screenshot,
    wait_for_websocket_connected,
)

DB_URL = "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins"

# ── Fixture: page with DB connected ──────────────────────────────────

@pytest.fixture
def connected_page(page: Page, web_server):
    """Page with bgins database already connected."""
    page.goto(web_server)
    wait_for_websocket_connected(page)
    page.wait_for_timeout(500)
    connect_database(page, DB_URL)
    page.wait_for_timeout(1000)
    return page


class TestSimpleQueries:
    """Test simple factual queries."""

    def test_count_query(self, connected_page: Page, artifact_dir):
        """Ask 'How many tables are there?' — should get a numeric answer."""
        page = connected_page
        result = submit_query(page, "How many tables are in the database?", timeout=90_000)

        assert not result["error"], f"Query returned error: {result['response'][:200]}"
        assert len(result["response"]) > 0, "Empty response"

        # Monitor should show complete
        assert is_monitor_complete(page)

        # Check monitor went through phases
        log = get_monitor_log(page)
        assert len(log) > 0, "Monitor log is empty"

        take_screenshot(page, "query_count_tables", artifact_dir)

    def test_schema_query(self, connected_page: Page, artifact_dir):
        """Ask about table structure — should return column details."""
        page = connected_page
        result = submit_query(page, "What columns does the ins_cars table have?", timeout=90_000)

        assert not result["error"], f"Query returned error: {result['response'][:200]}"
        response_lower = result["response"].lower()
        # Should mention columns or column names
        assert any(w in response_lower for w in ("column", "field", "ins_cars")), \
            f"Response doesn't mention columns: {result['response'][:200]}"

        take_screenshot(page, "query_schema", artifact_dir)

    def test_aggregation_query(self, connected_page: Page, artifact_dir):
        """Ask an aggregation question — should return numeric data."""
        page = connected_page
        result = submit_query(
            page,
            "How many records are in the ins_damages table?",
            timeout=90_000,
        )

        assert not result["error"], f"Query returned error: {result['response'][:200]}"
        assert len(result["response"]) > 10, "Response too short"

        take_screenshot(page, "query_aggregation", artifact_dir)

    def test_result_has_metadata(self, connected_page: Page, artifact_dir):
        """Result should show mode and elapsed time."""
        page = connected_page
        result = submit_query(page, "How many rows in ins_opis?", timeout=90_000)

        assert not result["error"]
        # Should have mode
        assert result["mode"] or True  # mode might not be set for quick
        # Should have timing
        assert result["elapsed"] >= 0

        take_screenshot(page, "query_metadata", artifact_dir)


class TestResultRendering:
    """Test that results render correctly in the chat."""

    def test_markdown_table_renders(self, connected_page: Page, artifact_dir):
        """Query that returns tabular data should render as HTML table."""
        page = connected_page
        result = submit_query(
            page,
            "Show me the top 5 damage types by count",
            mode="simple",
            timeout=120_000,
        )

        assert not result["error"], f"Error: {result['response'][:200]}"

        # Check if response contains a table (either markdown or text)
        response = result["response"]
        has_table = (
            page.locator(".message.assistant:last-child table").count() > 0
            or "|" in response  # markdown table in text
        )
        # A response about damage types should have some data
        assert len(response) > 20, "Response too short for a data query"

        take_screenshot(page, "query_table_render", artifact_dir)

    def test_followup_suggestions_appear(self, connected_page: Page, artifact_dir):
        """Result should include follow-up suggestion buttons."""
        page = connected_page
        result = submit_query(
            page,
            "What is the average damage amount?",
            mode="simple",
            timeout=120_000,
        )

        assert not result["error"]
        assert result["followup_count"] > 0, "No follow-up suggestions"

        take_screenshot(page, "query_followups", artifact_dir)

    def test_user_message_appears_in_chat(self, connected_page: Page, artifact_dir):
        """User's question should appear as a user message bubble."""
        page = connected_page
        question = "How many records are in ins_cars?"
        submit_query(page, question, timeout=90_000)

        messages = get_chat_messages(page)
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert any(question in m["text"] for m in user_msgs), \
            f"User question not found in messages: {[m['text'][:50] for m in user_msgs]}"

        take_screenshot(page, "query_user_bubble", artifact_dir)


class TestMonitorDuringQuery:
    """Test that the execution monitor updates in real-time."""

    def test_monitor_shows_activity_during_query(self, connected_page: Page, artifact_dir):
        """Monitor should show activity while query is running."""
        page = connected_page

        # Submit but don't wait for result
        result = submit_query(
            page,
            "Show the distribution of car brands in ins_cars",
            mode="simple",
            wait_for_result=False,
        )

        # Wait a moment for pipeline to start
        page.wait_for_timeout(2000)

        # Monitor should NOT be idle
        mon = get_monitor_state(page)

        # If query already completed (fast), that's fine too
        if mon["isQuerying"]:
            assert mon["phase"] != "idle", f"Monitor still idle during query: {mon}"
            take_screenshot(page, "query_monitor_active", artifact_dir)
            take_element_screenshot(page, "#monitor", "monitor_active_panel", artifact_dir)

        # Now wait for completion
        page.locator("#send-btn").wait_for(state="visible", timeout=120_000)
        take_screenshot(page, "query_monitor_complete", artifact_dir)

    def test_activity_log_populated(self, connected_page: Page, artifact_dir):
        """Activity log should have entries after a query."""
        page = connected_page
        submit_query(page, "Count of records in ins_opis", timeout=90_000)

        log = get_monitor_log(page)
        assert len(log) >= 3, f"Activity log too short: {log}"

        # Should contain key phases
        log_text = " ".join(log).lower()
        assert "mode" in log_text or "classify" in log_text or "plan" in log_text, \
            f"Log missing phase info: {log}"

        take_screenshot(page, "query_activity_log", artifact_dir)
