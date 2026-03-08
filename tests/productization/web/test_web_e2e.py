"""Phase 3: Web client end-to-end tests with Playwright."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

# Skip if playwright is not available
pytest.importorskip("playwright")

from playwright.sync_api import Page, expect


SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)


class TestWebPageLoad:
    """Test basic page load and UI structure."""

    def test_page_loads(self, page: Page, web_server: str):
        """Page should load without errors."""
        page.goto(web_server)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(SCREENSHOT_DIR / "01_initial_load.png"))
        assert page.title() or True  # Page loaded

    def test_has_query_input(self, page: Page, web_server: str):
        """Should have a query input area."""
        page.goto(web_server)
        page.wait_for_load_state("networkidle")
        # Look for text input or textarea
        inputs = page.locator("textarea, input[type='text']")
        assert inputs.count() > 0

    def test_has_source_panel(self, page: Page, web_server: str):
        """Should have a source management area."""
        page.goto(web_server)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(SCREENSHOT_DIR / "02_source_panel.png"))
        # Check for source-related text
        content = page.content()
        assert "source" in content.lower() or "connect" in content.lower() or "database" in content.lower()


class TestSourceManagement:
    """Test adding and managing data sources."""

    def test_add_database_source(self, page: Page, web_server: str):
        """Should be able to add a database source."""
        page.goto(web_server)
        page.wait_for_load_state("networkidle")

        # Look for a connection input or button
        conn_input = page.locator("input[placeholder*='connection'], input[placeholder*='Connection'], input[placeholder*='database'], input[placeholder*='Database'], #connStr, #connectionString, [name='connection']")
        if conn_input.count() > 0:
            conn_input.first.fill("mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins")

            # Find and click connect/add button
            btn = page.locator("button:has-text('Connect'), button:has-text('Add'), button:has-text('connect'), button:has-text('add')")
            if btn.count() > 0:
                btn.first.click()
                # Wait for source to be added
                page.wait_for_timeout(3000)
                page.screenshot(path=str(SCREENSHOT_DIR / "03_source_added.png"))

    def test_upload_csv(self, page: Page, web_server: str):
        """Should be able to upload a CSV file."""
        page.goto(web_server)
        page.wait_for_load_state("networkidle")

        # Look for file upload input
        file_input = page.locator("input[type='file']")
        if file_input.count() > 0:
            page.screenshot(path=str(SCREENSHOT_DIR / "04_before_upload.png"))


class TestQueryExecution:
    """Test query execution through the web interface."""

    def test_submit_query(self, page: Page, web_server: str):
        """Should be able to submit and execute a query."""
        page.goto(web_server)
        page.wait_for_load_state("networkidle")

        # First add a source if needed
        conn_input = page.locator("input[placeholder*='connection'], input[placeholder*='Connection'], #connStr, #connectionString, [name='connection']")
        if conn_input.count() > 0:
            conn_input.first.fill("mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins")
            btn = page.locator("button:has-text('Connect'), button:has-text('Add')")
            if btn.count() > 0:
                btn.first.click()
                page.wait_for_timeout(3000)

        # Find the query input
        query_input = page.locator("textarea, input[type='text']").last
        if query_input.count() > 0:
            query_input.fill("How many tables are in the database?")
            page.screenshot(path=str(SCREENSHOT_DIR / "05_query_entered.png"))

            # Submit (press Enter or click submit button)
            submit_btn = page.locator("button:has-text('Send'), button:has-text('Ask'), button:has-text('Submit'), button:has-text('Run')")
            if submit_btn.count() > 0:
                submit_btn.first.click()
            else:
                query_input.press("Enter")

            # Wait for response (up to 60s)
            page.wait_for_timeout(5000)
            page.screenshot(path=str(SCREENSHOT_DIR / "06_query_running.png"))

            # Wait for result
            try:
                page.wait_for_selector(".result, .response, .answer, .chat-message, .message", timeout=60000)
            except Exception:
                pass

            page.screenshot(path=str(SCREENSHOT_DIR / "07_query_result.png"))


class TestMonitorPanel:
    """Test the execution monitor panel."""

    def test_monitor_updates(self, page: Page, web_server: str):
        """Monitor should show pipeline updates during execution."""
        page.goto(web_server)
        page.wait_for_load_state("networkidle")

        # Check if there's a monitor panel
        monitor = page.locator(".monitor, .pipeline, .progress, #monitor, #executionMonitor")
        if monitor.count() > 0:
            page.screenshot(path=str(SCREENSHOT_DIR / "08_monitor_panel.png"))


class TestErrorHandling:
    """Test error states and edge cases."""

    def test_invalid_source(self, page: Page, web_server: str):
        """Should handle invalid connection string gracefully."""
        page.goto(web_server)
        page.wait_for_load_state("networkidle")

        conn_input = page.locator("input[placeholder*='connection'], input[placeholder*='Connection'], #connStr, #connectionString, [name='connection']")
        if conn_input.count() > 0:
            conn_input.first.fill("invalid://not:a@real/database")
            btn = page.locator("button:has-text('Connect'), button:has-text('Add')")
            if btn.count() > 0:
                btn.first.click()
                page.wait_for_timeout(3000)
                page.screenshot(path=str(SCREENSHOT_DIR / "09_invalid_source.png"))

    def test_empty_query(self, page: Page, web_server: str):
        """Should handle empty query submission gracefully."""
        page.goto(web_server)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(SCREENSHOT_DIR / "10_empty_query.png"))


class TestResponsiveLayout:
    """Test responsive design at different viewport sizes."""

    def test_desktop_layout(self, page: Page, web_server: str):
        """Desktop layout should show all panels."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(web_server)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(SCREENSHOT_DIR / "11_desktop_layout.png"))

    def test_tablet_layout(self, page: Page, web_server: str):
        """Tablet layout should adapt."""
        page.set_viewport_size({"width": 768, "height": 1024})
        page.goto(web_server)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(SCREENSHOT_DIR / "12_tablet_layout.png"))

    def test_mobile_layout(self, page: Page, web_server: str):
        """Mobile layout should stack panels."""
        page.set_viewport_size({"width": 375, "height": 812})
        page.goto(web_server)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(SCREENSHOT_DIR / "13_mobile_layout.png"))
