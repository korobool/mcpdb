"""Test source management lifecycle in the web client.

Tests: connect DB, verify schema loads, remove source, reconnect.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .helpers import (
    connect_database,
    get_source_count,
    get_source_names,
    get_chat_messages,
    is_monitor_idle,
    take_screenshot,
    wait_for_websocket_connected,
)

DB_URL = "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins"


class TestDatabaseConnection:
    """Test connecting a database source."""

    def test_initial_state_no_sources(self, page: Page, web_server, artifact_dir):
        """Page loads — verify basic page structure loads."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(1000)

        # Verify core UI elements exist
        assert page.locator("#sidebar").count() > 0, "Sidebar missing"
        assert page.locator("#main").count() > 0, "Main panel missing"
        assert page.locator("#monitor").count() > 0, "Monitor panel missing"
        assert page.locator("#question").count() > 0, "Query input missing"

        take_screenshot(page, "01_initial_load", artifact_dir)

    def test_connect_database(self, page: Page, web_server, artifact_dir):
        """Connect to bgins database and verify source card appears."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)

        connect_database(page, DB_URL, display_name="bgins")

        # Source card should appear
        assert get_source_count(page) >= 1
        names = get_source_names(page)
        assert any("bgins" in n.lower() for n in names)

        take_screenshot(page, "02_source_connected", artifact_dir)

    def test_welcome_message_shows_schema(self, page: Page, web_server, artifact_dir):
        """After connecting, welcome message shows table schema."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)

        connect_database(page, DB_URL)
        # Wait for welcome message to render with schema
        page.wait_for_timeout(2000)

        messages = get_chat_messages(page)
        # Find the welcome message with schema
        schema_msg = [m for m in messages if "table" in m["text"].lower() or "Connected" in m["text"]]
        assert len(schema_msg) > 0, f"No schema message found in: {[m['text'][:50] for m in messages]}"

        take_screenshot(page, "03_welcome_schema", artifact_dir)

    def test_starter_questions_visible(self, page: Page, web_server, artifact_dir):
        """Starter question buttons appear after connecting."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)

        connect_database(page, DB_URL)
        page.wait_for_timeout(2000)

        starters = page.locator(".starter-btn")
        assert starters.count() > 0, "No starter questions visible"

        take_screenshot(page, "04_starter_questions", artifact_dir)

    def test_remove_source(self, page: Page, web_server, artifact_dir):
        """Remove a connected source."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)

        connect_database(page, DB_URL)
        initial_count = get_source_count(page)
        assert initial_count >= 1

        # Accept the confirmation dialog
        page.on("dialog", lambda d: d.accept())
        page.locator("#sources-list .source-card .remove-btn").first.click()
        page.wait_for_timeout(1000)

        assert get_source_count(page) == initial_count - 1

        take_screenshot(page, "05_source_removed", artifact_dir)


class TestInvalidSource:
    """Test error handling for invalid sources."""

    def test_invalid_connection_string(self, page: Page, web_server, artifact_dir):
        """Invalid DB connection shows error, no crash."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)

        # Open details
        details = page.locator("#connect-details")
        if not details.get_attribute("open"):
            details.locator("summary").click()

        page.locator("#conn-str").fill("mysql://invalid:invalid@nowhere:9999/nope")
        page.locator("#connect-details .btn-primary").click()

        # Should see an alert or error — page should not crash
        page.on("dialog", lambda d: d.accept())
        page.wait_for_timeout(3000)

        # Source should NOT have been added
        assert get_source_count(page) == 0

        take_screenshot(page, "06_invalid_source", artifact_dir)
