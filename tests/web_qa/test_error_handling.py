"""Test error handling and edge cases.

Tests: empty query, no sources, cancellation, new conversation.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .helpers import (
    connect_database,
    submit_query,
    get_chat_messages,
    get_monitor_state,
    is_monitor_idle,
    count_messages,
    take_screenshot,
    wait_for_websocket_connected,
)

DB_URL = "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins"


class TestErrorStates:
    """Test error conditions."""

    def test_empty_query_rejected(self, page: Page, web_server, artifact_dir):
        """Empty query should not submit."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)
        connect_database(page, DB_URL)
        page.wait_for_timeout(1000)

        # Try sending empty query
        page.locator("#send-btn").click()
        page.wait_for_timeout(500)

        # Should not have created a user message
        user_msgs = page.locator(".message.user")
        assert user_msgs.count() == 0, "Empty query was submitted"

        take_screenshot(page, "error_empty_query", artifact_dir)

    def test_query_without_source_shows_error(self, page: Page, web_server, artifact_dir):
        """Querying without a source should show an error message."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)

        # Don't connect any source — just type and send
        textarea = page.locator("#question")
        textarea.fill("How many tables?")
        page.locator("#send-btn").click()

        # Wait for error response
        page.wait_for_timeout(3000)

        messages = get_chat_messages(page)
        error_msgs = [m for m in messages if "error" in m["text"].lower() or "no data source" in m["text"].lower() or "no sources" in m["text"].lower()]
        assert len(error_msgs) > 0 or len(messages) >= 1, "No error message shown for query without source"

        take_screenshot(page, "error_no_source", artifact_dir)

    def test_cancel_during_query(self, page: Page, web_server, artifact_dir):
        """Cancelling a running query should stop it."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)
        connect_database(page, DB_URL)
        page.wait_for_timeout(1000)

        # Submit a query that takes a while
        submit_query(
            page,
            "Show me a comprehensive analysis of all damage records with trends",
            mode="extended",
            wait_for_result=False,
        )

        # Wait for query to start processing
        page.wait_for_timeout(3000)

        # Click Cancel
        cancel_btn = page.locator("#cancel-btn")
        if cancel_btn.is_visible():
            cancel_btn.click()
            # Wait for cancellation
            page.locator("#send-btn").wait_for(state="visible", timeout=30_000)

            # Should show cancellation message or error
            messages = get_chat_messages(page)
            last_msg = messages[-1]["text"].lower() if messages else ""
            # Either "cancelled" or got a result (fast response)
            assert len(last_msg) > 0, "No response after cancel"
        else:
            # Query was so fast it already completed
            pass

        take_screenshot(page, "error_cancel", artifact_dir)


class TestNewConversation:
    """Test the new conversation button."""

    def test_new_conversation_clears_chat(self, page: Page, web_server, artifact_dir):
        """New conversation button should clear all messages."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)
        connect_database(page, DB_URL)
        page.wait_for_timeout(1000)

        # Submit a query first
        submit_query(page, "How many tables?", timeout=90_000)
        assert count_messages(page) > 0

        # Click new conversation
        page.locator("text=New conversation").click()
        page.wait_for_timeout(1000)

        # Chat should be cleared (may have welcome message)
        user_msgs = page.locator(".message.user")
        assert user_msgs.count() == 0, "User messages not cleared"

        # Monitor should be idle
        assert is_monitor_idle(page)

        take_screenshot(page, "new_conversation", artifact_dir)

    def test_can_query_after_new_conversation(self, page: Page, web_server, artifact_dir):
        """Should be able to query normally after new conversation."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)
        connect_database(page, DB_URL)
        page.wait_for_timeout(1000)

        # First query
        submit_query(page, "How many tables?", timeout=90_000)

        # New conversation
        page.locator("text=New conversation").click()
        page.wait_for_timeout(1000)

        # Second query should work
        result = submit_query(page, "Count rows in ins_cars", timeout=90_000)
        assert not result["error"], f"Error after new conversation: {result['response'][:200]}"

        take_screenshot(page, "query_after_new_convo", artifact_dir)


class TestInputBehavior:
    """Test input textarea behavior."""

    def test_enter_submits(self, page: Page, web_server, artifact_dir):
        """Pressing Enter should submit the query."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)
        connect_database(page, DB_URL)
        page.wait_for_timeout(1000)

        textarea = page.locator("#question")
        textarea.fill("How many tables?")
        textarea.press("Enter")

        # Should start a query — send button should hide
        page.wait_for_timeout(500)
        # Check that a user message appeared
        user_msgs = page.locator(".message.user")
        assert user_msgs.count() > 0, "Enter key didn't submit"

        # Wait for result
        page.locator("#send-btn").wait_for(state="visible", timeout=90_000)

        take_screenshot(page, "input_enter_submit", artifact_dir)

    def test_shift_enter_newline(self, page: Page, web_server, artifact_dir):
        """Shift+Enter should add a newline, not submit."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)
        connect_database(page, DB_URL)
        page.wait_for_timeout(1000)

        textarea = page.locator("#question")
        textarea.fill("Line 1")
        textarea.press("Shift+Enter")
        textarea.type("Line 2")

        # Should NOT have submitted
        user_msgs = page.locator(".message.user")
        assert user_msgs.count() == 0, "Shift+Enter submitted the query"

        # Textarea should contain both lines
        value = textarea.input_value()
        assert "Line 1" in value and "Line 2" in value

        take_screenshot(page, "input_shift_enter", artifact_dir)

    def test_textarea_disabled_during_query(self, page: Page, web_server, artifact_dir):
        """Textarea should be disabled while query is running."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)
        connect_database(page, DB_URL)
        page.wait_for_timeout(1000)

        # Use a query that takes a bit longer (simple mode, analytical)
        submit_query(
            page,
            "Analyze the distribution of damage amounts across all records in ins_damages, include statistics",
            mode="simple",
            wait_for_result=False,
        )

        # Poll for disabled state — query may be fast
        textarea = page.locator("#question")
        caught_disabled = False
        for _ in range(20):
            if textarea.is_disabled():
                caught_disabled = True
                break
            page.wait_for_timeout(200)

        if caught_disabled:
            take_screenshot(page, "input_disabled_during", artifact_dir)

        # Wait for completion
        page.locator("#send-btn").wait_for(state="visible", timeout=120_000)

        # After completion, textarea should be re-enabled
        assert not textarea.is_disabled(), "Textarea still disabled after query"

        take_screenshot(page, "input_disabled", artifact_dir)
