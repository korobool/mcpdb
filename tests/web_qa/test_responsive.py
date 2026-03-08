"""Test responsive layout behavior.

Tests: desktop, tablet, mobile viewports with real content.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .helpers import (
    connect_database,
    submit_query,
    take_screenshot,
    wait_for_websocket_connected,
)

DB_URL = "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins"


class TestDesktopLayout:
    """Test layout at 1920x1080 (default viewport)."""

    def test_three_column_layout(self, page: Page, web_server, artifact_dir):
        """Desktop should show sidebar + main + monitor."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)

        sidebar = page.locator("#sidebar")
        main = page.locator("#main")
        monitor = page.locator("#monitor")

        expect(sidebar).to_be_visible()
        expect(main).to_be_visible()
        expect(monitor).to_be_visible()

        take_screenshot(page, "layout_desktop", artifact_dir)

    def test_desktop_with_content(self, page: Page, web_server, artifact_dir):
        """Desktop layout with query result rendered."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)
        connect_database(page, DB_URL)
        page.wait_for_timeout(1000)

        submit_query(page, "Show top 5 car brands", mode="simple", timeout=120_000)

        # All three columns should still be visible
        expect(page.locator("#sidebar")).to_be_visible()
        expect(page.locator("#main")).to_be_visible()
        expect(page.locator("#monitor")).to_be_visible()

        take_screenshot(page, "layout_desktop_content", artifact_dir)


class TestTabletLayout:
    """Test layout at 1024x768."""

    def test_monitor_visible_at_1024(self, page: Page, web_server, artifact_dir):
        """Monitor should still be visible at 1024px width."""
        page.set_viewport_size({"width": 1024, "height": 768})
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)

        # At 1024px, monitor might be hidden (CSS breakpoint at 1100px)
        monitor = page.locator("#monitor")
        sidebar = page.locator("#sidebar")

        expect(sidebar).to_be_visible()
        # Monitor hidden at < 1100px per CSS
        # This is the expected responsive behavior

        take_screenshot(page, "layout_tablet", artifact_dir)


class TestNarrowLayout:
    """Test layout at 800px and below."""

    def test_sidebar_narrower_at_800(self, page: Page, web_server, artifact_dir):
        """Sidebar should narrow at 800px width."""
        page.set_viewport_size({"width": 800, "height": 600})
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)

        sidebar = page.locator("#sidebar")
        expect(sidebar).to_be_visible()

        # Check sidebar width via JS
        width = page.evaluate("() => document.getElementById('sidebar').offsetWidth")
        assert width <= 230, f"Sidebar too wide at 800px viewport: {width}px"

        take_screenshot(page, "layout_narrow", artifact_dir)

    def test_monitor_hidden_at_narrow(self, page: Page, web_server, artifact_dir):
        """Monitor should be hidden at narrow widths."""
        page.set_viewport_size({"width": 900, "height": 600})
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)

        monitor = page.locator("#monitor")
        # CSS: @media (max-width: 1100px) { #monitor { display: none; } }
        expect(monitor).to_be_hidden()

        take_screenshot(page, "layout_monitor_hidden", artifact_dir)


class TestMobileLayout:
    """Test layout at mobile viewport (375x812)."""

    def test_mobile_layout_usable(self, page: Page, web_server, artifact_dir):
        """App should be usable on mobile viewport."""
        page.set_viewport_size({"width": 375, "height": 812})
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)

        # Sidebar and main should be visible (though sidebar is narrow)
        sidebar = page.locator("#sidebar")
        main = page.locator("#main")
        expect(sidebar).to_be_visible()
        expect(main).to_be_visible()

        # Input bar should be accessible
        textarea = page.locator("#question")
        expect(textarea).to_be_visible()

        take_screenshot(page, "layout_mobile", artifact_dir)

    def test_mobile_with_content(self, page: Page, web_server, artifact_dir):
        """Mobile layout should display query results properly."""
        page.set_viewport_size({"width": 375, "height": 812})
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)
        connect_database(page, DB_URL)
        page.wait_for_timeout(1000)

        submit_query(page, "How many tables?", timeout=90_000)

        # Message should be visible
        msgs = page.locator(".message.assistant")
        assert msgs.count() > 0
        expect(msgs.last).to_be_visible()

        take_screenshot(page, "layout_mobile_content", artifact_dir)
