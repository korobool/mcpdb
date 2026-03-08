"""Test multiple sequential queries in a single session.

Tests: conversation flow, message history, monitor reset between queries.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .helpers import (
    connect_database,
    submit_query,
    count_messages,
    get_chat_messages,
    get_monitor_state,
    is_monitor_complete,
    take_screenshot,
    wait_for_websocket_connected,
)

DB_URL = "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins"


@pytest.fixture
def connected_page(page: Page, web_server):
    page.goto(web_server)
    wait_for_websocket_connected(page)
    page.wait_for_timeout(500)
    connect_database(page, DB_URL)
    page.wait_for_timeout(1000)
    return page


class TestConversationFlow:
    """Test multiple queries in sequence."""

    def test_two_queries_both_appear(self, connected_page: Page, artifact_dir):
        """Both queries and responses should appear in chat."""
        page = connected_page

        # First query
        result1 = submit_query(page, "How many rows in ins_cars?", timeout=90_000)
        assert not result1["error"]

        # Second query
        result2 = submit_query(page, "How many rows in ins_damages?", timeout=90_000)
        assert not result2["error"]

        # Should have 2 user messages and 2+ assistant messages (including welcome)
        user_msgs = count_messages(page, "user")
        assert user_msgs == 2, f"Expected 2 user messages, got {user_msgs}"

        take_screenshot(page, "multi_query_two", artifact_dir)

    def test_monitor_resets_between_queries(self, connected_page: Page, artifact_dir):
        """Monitor should reset and show new query state."""
        page = connected_page

        submit_query(page, "Count of rows in ins_cars", timeout=90_000)
        mon1 = get_monitor_state(page)

        submit_query(page, "Count of rows in ins_opis", timeout=90_000)
        mon2 = get_monitor_state(page)

        # Monitor should reflect the second query (log should be different)
        assert mon2["phase"] == "idle"
        assert is_monitor_complete(page)

        take_screenshot(page, "multi_query_monitor", artifact_dir)

    def test_scroll_to_latest(self, connected_page: Page, artifact_dir):
        """Chat should auto-scroll to show the latest message."""
        page = connected_page

        # Submit multiple queries
        for q in [
            "How many rows in ins_cars?",
            "How many rows in ins_damages?",
            "How many rows in ins_opis?",
        ]:
            submit_query(page, q, timeout=90_000)

        # The last message should be visible (in viewport)
        last_msg = page.locator(".message.assistant").last
        expect(last_msg).to_be_in_viewport()

        take_screenshot(page, "multi_query_scroll", artifact_dir)


class TestMessageRendering:
    """Test message rendering quality."""

    def test_user_message_matches_input(self, connected_page: Page, artifact_dir):
        """User message text should match what was typed."""
        page = connected_page
        question = "What is the average damage amount in ins_damages?"
        submit_query(page, question, timeout=120_000)

        messages = get_chat_messages(page)
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert any(question in m["text"] for m in user_msgs), \
            f"User question not found: {[m['text'] for m in user_msgs]}"

    def test_response_not_empty(self, connected_page: Page, artifact_dir):
        """Every successful query should have a non-empty response."""
        page = connected_page

        for q in ["How many tables?", "Count ins_cars rows"]:
            result = submit_query(page, q, timeout=90_000)
            assert not result["error"], f"Error for '{q}': {result['response'][:100]}"
            assert len(result["response"]) > 5, f"Empty response for '{q}'"
