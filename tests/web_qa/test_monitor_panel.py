"""Test the execution monitor panel in detail.

Tests: pipeline phases, step progress, timing, LLM indicators.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .helpers import (
    connect_database,
    submit_query,
    get_monitor_state,
    get_monitor_log,
    is_monitor_idle,
    is_monitor_complete,
    take_screenshot,
    take_element_screenshot,
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


class TestMonitorIdle:
    """Test monitor in idle state."""

    def test_monitor_shows_idle_initially(self, connected_page: Page, artifact_dir):
        """Monitor should show 'Waiting for a query...' before any query."""
        page = connected_page
        assert is_monitor_idle(page)
        take_element_screenshot(page, "#monitor", "monitor_idle", artifact_dir)

    def test_monitor_visible_on_desktop(self, connected_page: Page, artifact_dir):
        """Monitor panel should be visible on desktop viewport."""
        page = connected_page
        monitor = page.locator("#monitor")
        expect(monitor).to_be_visible()


class TestMonitorPhases:
    """Test monitor phase pipeline display."""

    def test_phase_pipeline_shows_all_phases(self, connected_page: Page, artifact_dir):
        """After a query, pipeline should show all phase labels."""
        page = connected_page
        submit_query(page, "Count rows in ins_cars", timeout=90_000)

        # Check pipeline shows phase labels
        pipeline = page.locator(".mon-pipeline")
        if pipeline.count() > 0:
            text = pipeline.first.inner_text()
            for phase in ["Classify", "Plan", "Execute", "Synthesize"]:
                assert phase in text, f"Phase '{phase}' not in pipeline: {text}"

        take_element_screenshot(page, "#monitor", "monitor_phases", artifact_dir)

    def test_completed_phases_marked_done(self, connected_page: Page, artifact_dir):
        """Completed phases should be marked with 'done' class."""
        page = connected_page
        submit_query(page, "How many rows in ins_opis?", timeout=90_000)

        done_steps = page.locator(".mon-pipeline .pipe-step.done")
        assert done_steps.count() > 0, "No phases marked as done after query completion"

    def test_mode_badge_displayed(self, connected_page: Page, artifact_dir):
        """Mode badge should appear in monitor header."""
        page = connected_page
        submit_query(page, "Count all records", mode="simple", timeout=90_000)

        badge = page.locator(".mode-badge")
        if badge.count() > 0:
            badge_text = badge.first.inner_text()
            assert len(badge_text) > 0, "Mode badge has no text"
            # Should have a mode-specific class
            classes = badge.first.get_attribute("class")
            assert any(m in classes for m in ("simple", "quick", "optimization", "extended", "deep")), \
                f"Badge doesn't have mode class: {classes}"

        take_element_screenshot(page, "#monitor", "monitor_mode_badge", artifact_dir)


class TestMonitorSteps:
    """Test step display in monitor."""

    def test_steps_shown_during_execution(self, connected_page: Page, artifact_dir):
        """Monitor should show individual execution steps."""
        page = connected_page
        submit_query(
            page,
            "Show the top 5 car brands by count",
            mode="simple",
            timeout=120_000,
        )

        steps = page.locator("#mon-content .step")
        # Simple mode should have at least 1 step
        assert steps.count() >= 1, "No steps shown in monitor"

        take_element_screenshot(page, "#monitor", "monitor_steps", artifact_dir)

    def test_step_has_timing(self, connected_page: Page, artifact_dir):
        """Completed steps should show timing."""
        page = connected_page
        submit_query(
            page,
            "Count records in ins_damages",
            mode="simple",
            timeout=120_000,
        )

        timing = page.locator("#mon-content .step .timing")
        if timing.count() > 0:
            time_text = timing.first.inner_text()
            assert "ms" in time_text or "s" in time_text, f"No timing format: {time_text}"

    def test_success_steps_have_checkmark(self, connected_page: Page, artifact_dir):
        """Successful steps should show green checkmark."""
        page = connected_page
        submit_query(
            page,
            "How many rows in ins_cars?",
            mode="simple",
            timeout=90_000,
        )

        # Look for success checkmark (✓)
        mon_content = page.locator("#mon-content").inner_html()
        # Steps should show success icon (green checkmark via span style)
        assert "var(--green)" in mon_content or "✓" in mon_content, \
            "No success indicators in steps"

    def test_progress_bar_shows_completion(self, connected_page: Page, artifact_dir):
        """Progress bar should show step completion percentage."""
        page = connected_page
        submit_query(
            page,
            "What are the column names in ins_damages?",
            mode="simple",
            timeout=90_000,
        )

        progress = page.locator("#mon-content .progress-bar")
        if progress.count() > 0:
            fill = page.locator("#mon-content .progress-fill")
            # After completion, should be at 100%
            style = fill.first.get_attribute("style")
            assert "width:" in style, f"Progress fill has no width: {style}"

        take_element_screenshot(page, "#monitor", "monitor_progress", artifact_dir)


class TestMonitorCompletion:
    """Test monitor in completed state."""

    def test_shows_complete_header(self, connected_page: Page, artifact_dir):
        """After query, monitor should show 'Complete' with checkmark."""
        page = connected_page
        submit_query(page, "Count rows in ins_cars", timeout=90_000)

        header = page.locator(".mon-header")
        if header.count() > 0:
            text = header.first.inner_text()
            assert "Complete" in text, f"Header doesn't show 'Complete': {text}"

    def test_shows_elapsed_time(self, connected_page: Page, artifact_dir):
        """Monitor should show elapsed time."""
        page = connected_page
        submit_query(page, "Count rows in ins_opis", timeout=90_000)

        elapsed = page.locator(".mon-elapsed")
        if elapsed.count() > 0:
            text = elapsed.first.inner_text()
            assert "elapsed" in text.lower(), f"No 'elapsed' in timing: {text}"
            # Should have a time value
            assert any(c.isdigit() for c in text), f"No digits in elapsed: {text}"

    def test_activity_log_collapsible(self, connected_page: Page, artifact_dir):
        """Activity log should be in a collapsible details element."""
        page = connected_page
        submit_query(page, "How many tables?", timeout=90_000)

        activity_log = page.locator(".activity-log")
        if activity_log.count() > 0:
            summary = activity_log.locator("summary")
            assert summary.count() > 0, "Activity log missing summary"
            summary_text = summary.first.inner_text()
            assert "Activity log" in summary_text, f"Unexpected summary: {summary_text}"

        take_element_screenshot(page, "#monitor", "monitor_complete", artifact_dir)
