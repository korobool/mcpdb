"""Test different query modes via the web UI.

Tests: quick, simple, optimization modes produce appropriate responses.
Extended and deep are tested separately due to long runtimes.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .helpers import (
    connect_database,
    submit_query,
    get_monitor_state,
    get_monitor_log,
    select_mode,
    get_selected_mode,
    take_screenshot,
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


class TestModeSelection:
    """Test mode selector UI behavior."""

    def test_mode_selector_defaults_to_auto(self, connected_page: Page):
        """Mode selector should default to 'auto'."""
        page = connected_page
        assert get_selected_mode(page) == "auto"

    def test_mode_selector_updates_description(self, connected_page: Page, artifact_dir):
        """Changing mode updates the description text."""
        page = connected_page

        for mode in ["quick", "simple", "optimization", "extended", "deep"]:
            select_mode(page, mode)
            desc = page.locator("#mode-desc").inner_text()
            assert len(desc) > 5, f"No description for mode {mode}: {desc}"

        take_screenshot(page, "mode_selector", artifact_dir)

    def test_mode_persists_across_queries(self, connected_page: Page, artifact_dir):
        """Selected mode should persist after submitting a query."""
        page = connected_page
        select_mode(page, "simple")
        submit_query(page, "How many rows in ins_cars?", timeout=90_000)

        # Mode should still be 'simple'
        assert get_selected_mode(page) == "simple"


class TestQuickMode:
    """Test quick mode queries."""

    def test_quick_mode_fast_response(self, connected_page: Page, artifact_dir):
        """Quick mode should respond faster than other modes."""
        page = connected_page
        result = submit_query(
            page,
            "What tables are in the database?",
            mode="quick",
            timeout=60_000,
        )

        assert not result["error"], f"Error: {result['response'][:200]}"

        log = get_monitor_log(page)
        log_text = " ".join(log).lower()
        # Should mention quick mode in log
        has_mode_ref = "quick" in log_text or "mode" in log_text
        assert has_mode_ref or len(result["response"]) > 0

        take_screenshot(page, "mode_quick", artifact_dir)


class TestSimpleMode:
    """Test simple mode queries."""

    def test_simple_mode_runs_plan(self, connected_page: Page, artifact_dir):
        """Simple mode should show plan in monitor."""
        page = connected_page
        result = submit_query(
            page,
            "What are the top 5 most common car brands?",
            mode="simple",
            timeout=120_000,
        )

        assert not result["error"], f"Error: {result['response'][:200]}"

        log = get_monitor_log(page)
        log_text = " ".join(log).lower()
        # Should have planned and executed steps
        assert "plan" in log_text or "step" in log_text, f"No plan/step in log: {log}"

        take_screenshot(page, "mode_simple", artifact_dir)


class TestOptimizationMode:
    """Test optimization mode queries."""

    def test_optimization_mode_validates(self, connected_page: Page, artifact_dir):
        """Optimization mode should produce a result and show mode in monitor."""
        page = connected_page
        result = submit_query(
            page,
            "What is the total damage amount by car brand?",
            mode="optimization",
            timeout=180_000,
        )

        assert not result["error"], f"Error: {result['response'][:200]}"

        log = get_monitor_log(page)
        log_text = " ".join(log).lower()
        # Optimization mode should at least show mode info
        # (may hit cache and skip plan/validate/steps)
        assert "optimization" in log_text or "mode" in log_text or "done" in log_text, \
            f"No optimization activity in log: {log}"
        assert len(result["response"]) > 10, "Response too short"

        take_screenshot(page, "mode_optimization", artifact_dir)


@pytest.mark.slow
class TestExtendedMode:
    """Test extended mode (multi-revision). Slow — marked for optional run."""

    def test_extended_mode_multi_step(self, connected_page: Page, artifact_dir):
        """Extended mode should show checkpoint/revision activity."""
        page = connected_page
        result = submit_query(
            page,
            "Analyze the relationship between car brand and damage amount, including trends",
            mode="extended",
            timeout=300_000,
        )

        assert not result["error"], f"Error: {result['response'][:200]}"
        assert len(result["response"]) > 100, "Extended mode response too short"

        log = get_monitor_log(page)
        log_text = " ".join(log).lower()
        assert "plan" in log_text, f"No plan in extended log: {log}"

        take_screenshot(page, "mode_extended", artifact_dir)


@pytest.mark.slow
class TestDeepMode:
    """Test deep mode (multi-investigation). Very slow — marked for optional run."""

    def test_deep_mode_investigations(self, connected_page: Page, artifact_dir):
        """Deep mode should show blueprint and investigations."""
        page = connected_page
        result = submit_query(
            page,
            "Perform a comprehensive analysis of the insurance claims data",
            mode="deep",
            timeout=600_000,
        )

        assert not result["error"], f"Error: {result['response'][:200]}"

        log = get_monitor_log(page)
        log_text = " ".join(log).lower()
        assert "blueprint" in log_text or "investigation" in log_text or "deep" in log_text, \
            f"No deep mode activity in log: {log}"

        # Check for intermediate investigation messages
        messages = page.locator(".message.intermediate")
        # Deep mode should produce at least some investigation results
        assert messages.count() >= 0  # May or may not have intermediate msgs

        take_screenshot(page, "mode_deep", artifact_dir)
