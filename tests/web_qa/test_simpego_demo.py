"""Simpego CSV demo scenario — upload two CSV files, run analytical queries.

Run with:
    pytest tests/web_qa/test_simpego_demo.py --visible --record-video -v -s
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from .helpers import (
    get_chat_messages,
    get_monitor_log,
    get_monitor_state,
    is_monitor_complete,
    take_screenshot,
    take_element_screenshot,
    wait_for_websocket_connected,
)

CLAIMS_CSV = Path.home() / "Downloads" / "claims_simpego_v2.csv"
POLICIES_CSV = Path.home() / "Downloads" / "policies_simpego_v2.csv"
OUTPUT_DIR = Path.home() / "web_qa_simpego"

pytestmark = pytest.mark.skipif(
    not CLAIMS_CSV.exists() or not POLICIES_CSV.exists(),
    reason="Simpego CSV files not found in ~/Downloads",
)


@pytest.fixture(scope="module", autouse=True)
def output_dir():
    """Create output directory for screenshots."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "screenshots").mkdir(exist_ok=True)
    return OUTPUT_DIR


def _screenshot(page: Page, name: str):
    """Save screenshot to both artifacts and home output dir."""
    path = OUTPUT_DIR / "screenshots" / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)


def _element_screenshot(page: Page, selector: str, name: str):
    """Save element screenshot to home output dir."""
    path = OUTPUT_DIR / "screenshots" / f"{name}.png"
    el = page.locator(selector)
    if el.count() > 0:
        el.first.screenshot(path=str(path))


class TestSimpegoDemo:
    """Full demo: upload CSVs, run 3 analytical queries."""

    def test_01_load_page(self, page: Page, web_server):
        """Load the web page and verify it's ready."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(1000)

        expect(page.locator("#sidebar")).to_be_visible()
        expect(page.locator("#question")).to_be_visible()

        _screenshot(page, "01_initial_page")

    def test_02_upload_csv_files(self, page: Page, web_server):
        """Upload both CSV files via the sidebar."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(1000)

        # Open CSV upload section
        csv_details = page.locator("#csv-details")
        csv_details.locator("summary").click()
        page.wait_for_timeout(500)

        _screenshot(page, "02_csv_upload_open")

        # Set files on the file input (Playwright can set files directly)
        file_input = page.locator("#csv-files")
        file_input.set_input_files([str(CLAIMS_CSV), str(POLICIES_CSV)])
        page.wait_for_timeout(500)

        _screenshot(page, "03_files_staged")

        # Set display name
        page.locator("#csv-name").fill("Simpego Insurance")

        # Click Upload
        page.locator("#csv-upload-btn").click()

        # Wait for upload to complete — the policies file is 364MB so be patient
        # Watch for source card to appear (upload + processing done)
        page.locator("#sources-list .source-card").first.wait_for(
            state="visible", timeout=300_000,
        )

        _screenshot(page, "04_upload_complete")

        # Verify source card
        source_text = page.locator("#sources-list").inner_text()
        assert "Simpego" in source_text or "simpego" in source_text.lower() or \
            page.locator("#sources-list .source-card").count() > 0, \
            f"Source not found: {source_text}"

        # Wait for welcome message with schema
        page.wait_for_timeout(3000)
        _screenshot(page, "05_welcome_with_schema")

    def test_03_query_relations(self, page: Page, web_server):
        """Query 1: Analyse data for potential relations between tables."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(1000)

        # Check if source is still connected (session-scoped server)
        if page.locator("#sources-list .source-card").count() == 0:
            pytest.skip("Source not connected — run test_02 first")

        # Set mode to simple for a balanced analysis
        page.locator("#mode-select").select_option("simple")

        # Type and send query
        question = "Analyse data for potential relations between tables"
        page.locator("#question").fill(question)
        _screenshot(page, "06_query1_typed")

        page.locator("#send-btn").click()

        # Wait a few seconds then screenshot the monitor mid-execution
        page.wait_for_timeout(5000)
        _screenshot(page, "07_query1_monitor_active")
        _element_screenshot(page, "#monitor", "07a_monitor_panel")

        # Wait for result (generous timeout — large CSV analysis)
        page.locator("#send-btn").wait_for(state="visible", timeout=600_000)

        _screenshot(page, "08_query1_result")
        _element_screenshot(page, "#monitor", "08a_monitor_complete")

        # Verify we got a meaningful response
        msgs = get_chat_messages(page)
        assistant_msgs = [m for m in msgs if m["role"] == "assistant" and not m.get("isIntermediate")]
        last_response = assistant_msgs[-1]["text"] if assistant_msgs else ""
        assert len(last_response) > 50, f"Response too short: {last_response[:100]}"

        # Check for tables in response
        tables_in_response = page.locator(".message.assistant:last-child table")
        if tables_in_response.count() > 0:
            _element_screenshot(page, ".message.assistant:last-child", "08b_response_detail")

    def test_04_query_correlation_plots(self, page: Page, web_server):
        """Query 2: Build two cross correlation plots for numerical data."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(1000)

        if page.locator("#sources-list .source-card").count() == 0:
            pytest.skip("Source not connected — run test_02 first")

        page.locator("#mode-select").select_option("simple")

        question = "Build two cross correlation plots for numerical data one per table"
        page.locator("#question").fill(question)
        _screenshot(page, "09_query2_typed")

        page.locator("#send-btn").click()

        page.wait_for_timeout(5000)
        _screenshot(page, "10_query2_executing")

        # Wait for result (large CSV — correlation can take a while)
        page.locator("#send-btn").wait_for(state="visible", timeout=600_000)

        _screenshot(page, "11_query2_result")

        # Check for chart images
        charts = page.locator(".message.assistant:last-child .chart-artifact img")
        if charts.count() > 0:
            _screenshot(page, "12_query2_charts")
            # Screenshot each chart individually
            for i in range(min(charts.count(), 4)):
                chart_path = OUTPUT_DIR / "screenshots" / f"12_chart_{i+1}.png"
                charts.nth(i).screenshot(path=str(chart_path))
        else:
            # Check for inline images in markdown
            imgs = page.locator(".message.assistant:last-child img")
            if imgs.count() > 0:
                _screenshot(page, "12_query2_inline_charts")

        # Verify response
        msgs = get_chat_messages(page)
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        last = assistant_msgs[-1]["text"] if assistant_msgs else ""
        assert len(last) > 30, f"Response too short: {last[:100]}"

    def test_05_query_eda_actuary(self, page: Page, web_server):
        """Query 3: Perform EDA as an actuary."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(1000)

        if page.locator("#sources-list .source-card").count() == 0:
            pytest.skip("Source not connected — run test_02 first")

        # Use extended mode for a thorough actuarial analysis
        page.locator("#mode-select").select_option("extended")

        question = "Perform EDA as an actuary"
        page.locator("#question").fill(question)
        _screenshot(page, "13_query3_typed")

        page.locator("#send-btn").click()

        # Capture monitor at various stages
        page.wait_for_timeout(5000)
        _screenshot(page, "14_query3_classifying")

        page.wait_for_timeout(15000)
        _screenshot(page, "15_query3_executing")
        _element_screenshot(page, "#monitor", "15a_monitor_mid_execution")

        page.wait_for_timeout(30000)
        _screenshot(page, "16_query3_mid_analysis")

        # Wait for result — extended mode can take several minutes
        page.locator("#send-btn").wait_for(state="visible", timeout=600_000)

        _screenshot(page, "17_query3_result")
        _element_screenshot(page, "#monitor", "17a_monitor_final")

        # Check for charts
        charts = page.locator(".message.assistant:last-child .chart-artifact img")
        if charts.count() > 0:
            _screenshot(page, "18_query3_charts")
            for i in range(min(charts.count(), 6)):
                chart_path = OUTPUT_DIR / "screenshots" / f"18_eda_chart_{i+1}.png"
                charts.nth(i).screenshot(path=str(chart_path))

        # Verify thorough response
        msgs = get_chat_messages(page)
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        last = assistant_msgs[-1]["text"] if assistant_msgs else ""
        assert len(last) > 100, f"EDA response too short: {last[:100]}"

        # Final overview screenshot
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)
        _screenshot(page, "19_final_overview")

    def test_06_copy_videos(self, page: Page, web_server):
        """Copy recorded videos to output directory (runs last)."""
        video_src = Path(__file__).parent / "artifacts" / "videos"
        if not video_src.exists():
            pytest.skip("No videos recorded")

        videos = list(video_src.glob("*.webm"))
        if not videos:
            pytest.skip("No video files found")

        video_dest = OUTPUT_DIR / "videos"
        video_dest.mkdir(exist_ok=True)

        names = [
            "01_upload_csv",
            "02_upload_csv",  # page reloads create new contexts
            "03_relations_query",
            "04_correlation_plots",
            "05_eda_actuary",
            "06_copy",
        ]

        for i, v in enumerate(sorted(videos, key=lambda p: p.stat().st_mtime)):
            name = names[i] if i < len(names) else f"session_{i+1}"
            dest = video_dest / f"{name}.webm"
            shutil.copy2(v, dest)

        copied = list(video_dest.glob("*.webm"))
        assert len(copied) > 0, "No videos copied"
