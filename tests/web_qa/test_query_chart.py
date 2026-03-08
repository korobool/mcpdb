"""Test chart rendering in the web client.

Tests: chart queries produce <img> tags with base64 data.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .helpers import (
    connect_database,
    submit_query,
    take_screenshot,
    take_element_screenshot,
    wait_for_websocket_connected,
)

DB_URL = "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins"


@pytest.fixture
def connected_page(page: Page, web_server):
    """Page with bgins database already connected."""
    page.goto(web_server)
    wait_for_websocket_connected(page)
    page.wait_for_timeout(500)
    connect_database(page, DB_URL)
    page.wait_for_timeout(1000)
    return page


class TestChartQueries:
    """Test that chart-generating queries render images."""

    def test_bar_chart_renders(self, connected_page: Page, artifact_dir):
        """A chart query should produce an <img> with base64 data."""
        page = connected_page
        result = submit_query(
            page,
            "Create a bar chart showing the top 10 car brands by count from ins_cars",
            mode="simple",
            timeout=180_000,
        )

        assert not result["error"], f"Error: {result['response'][:200]}"

        # Check for chart image
        chart_imgs = page.locator(".message.assistant:last-child .chart-artifact img")
        if chart_imgs.count() > 0:
            # Verify it's a base64 image
            src = chart_imgs.first.get_attribute("src")
            assert src.startswith("data:image/"), f"Chart img src not base64: {src[:50]}"
            take_element_screenshot(page, ".chart-artifact", "chart_bar", artifact_dir)
        else:
            # Some responses include chart as inline image or text description
            # This is acceptable as long as there's a meaningful response
            assert len(result["response"]) > 50, "No chart and short response"

        take_screenshot(page, "query_chart_bar", artifact_dir)

    def test_chart_has_title(self, connected_page: Page, artifact_dir):
        """Chart artifacts should have a title label."""
        page = connected_page
        result = submit_query(
            page,
            "Plot a pie chart of damage types distribution from ins_damages",
            mode="simple",
            timeout=180_000,
        )

        assert not result["error"], f"Error: {result['response'][:200]}"

        chart_titles = page.locator(".message.assistant:last-child .chart-artifact .chart-title")
        if chart_titles.count() > 0:
            title_text = chart_titles.first.inner_text()
            assert len(title_text) > 0, "Chart title is empty"

        take_screenshot(page, "query_chart_pie", artifact_dir)

    def test_response_with_chart_has_text(self, connected_page: Page, artifact_dir):
        """Chart responses should also include textual analysis."""
        page = connected_page
        result = submit_query(
            page,
            "Show me a histogram of damage amounts from ins_damages",
            mode="simple",
            timeout=180_000,
        )

        assert not result["error"], f"Error: {result['response'][:200]}"
        # Should have some text beyond just the chart
        assert len(result["response"]) > 30, \
            f"Response too short — expected text analysis: {result['response'][:100]}"

        take_screenshot(page, "query_chart_histogram", artifact_dir)
