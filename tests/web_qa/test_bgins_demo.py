"""BGINS insurance demo — progressive data exploration in 5 acts.

Story: An analyst gets access to a Bulgarian auto insurance claims database
and explores it step by step — from orientation to deep analysis.

Run with:
    pytest tests/web_qa/test_bgins_demo.py --visible --record-video -v -s

Output:
    ~/web_qa_bgins/screenshots/   — key-moment PNGs
    ~/web_qa_bgins/videos/        — full session recordings
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from .helpers import (
    connect_database,
    get_chat_messages,
    get_monitor_log,
    get_monitor_state,
    is_monitor_complete,
    take_screenshot,
    take_element_screenshot,
    wait_for_websocket_connected,
)

DB_URL = "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins"
OUTPUT_DIR = Path.home() / "web_qa_bgins"


@pytest.fixture(scope="module", autouse=True)
def output_dir():
    """Create output directory for screenshots."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "screenshots").mkdir(exist_ok=True)
    return OUTPUT_DIR


def _shot(page: Page, name: str):
    """Save a full-page screenshot."""
    path = OUTPUT_DIR / "screenshots" / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)


def _element_shot(page: Page, selector: str, name: str):
    """Save an element screenshot if it exists."""
    path = OUTPUT_DIR / "screenshots" / f"{name}.png"
    el = page.locator(selector)
    if el.count() > 0:
        el.first.screenshot(path=str(path))


class TestBginsDemo:
    """5-act demo: orient → drill-down → trends → cross-analysis → EDA."""

    # ── Act 0: Setup ─────────────────────────────────────────────────

    def test_00_connect_database(self, page: Page, web_server):
        """Load page and connect to the bgins database."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(1000)

        _shot(page, "00_landing")

        # Connect database via sidebar
        connect_database(page, DB_URL)
        page.wait_for_timeout(3000)

        # Verify source appeared and ERD rendered
        expect(page.locator("#sources-list .source-card").first).to_be_visible()
        _shot(page, "01_connected_erd")
        _element_shot(page, ".mermaid", "01a_erd_diagram")

        # Verify the schema summary table is visible
        source_text = page.locator("#sources-list").inner_text()
        assert "bgins" in source_text.lower() or \
            page.locator("#sources-list .source-card").count() > 0

    # ── Act 1: Orient — "What do we have?" ───────────────────────────

    def test_01_orientation(self, page: Page, web_server):
        """Act 1: Overview of the database — tables, sizes, what's interesting."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(1000)

        if page.locator("#sources-list .source-card").count() == 0:
            pytest.skip("Source not connected — run test_00 first")

        page.locator("#mode-select").select_option("quick")

        question = (
            "Give me an overview: how many tables, total rows, "
            "and which are the main entity tables vs lookup tables?"
        )
        page.locator("#question").fill(question)
        _shot(page, "02_act1_question")

        page.locator("#send-btn").click()

        # Capture monitor in-flight
        page.wait_for_timeout(3000)
        _shot(page, "03_act1_processing")

        # Wait for result
        page.locator("#send-btn").wait_for(state="visible", timeout=120_000)

        _shot(page, "04_act1_result")
        _element_shot(page, "#monitor", "04a_monitor")

        # Verify meaningful response
        msgs = get_chat_messages(page)
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"
                          and not m.get("isIntermediate")]
        last = assistant_msgs[-1]["text"] if assistant_msgs else ""
        assert len(last) > 50, f"Response too short: {last[:100]}"

    # ── Act 2: Drill down — "Which brands drive the most claims?" ────

    def test_02_brand_claims(self, page: Page, web_server):
        """Act 2: Top car brands by claim count and average cost."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(1000)

        if page.locator("#sources-list .source-card").count() == 0:
            pytest.skip("Source not connected — run test_00 first")

        page.locator("#mode-select").select_option("simple")

        question = (
            "What are the top 10 car brands by number of insurance claims? "
            "Show the claim count, average total cost, and max single claim "
            "cost for each brand."
        )
        page.locator("#question").fill(question)
        _shot(page, "05_act2_question")

        page.locator("#send-btn").click()

        page.wait_for_timeout(5000)
        _shot(page, "06_act2_monitor")
        _element_shot(page, "#monitor", "06a_monitor_steps")

        page.locator("#send-btn").wait_for(state="visible", timeout=180_000)

        _shot(page, "07_act2_result")

        # Check for tables in response
        tables = page.locator(".message.assistant:last-child table")
        if tables.count() > 0:
            _element_shot(page, ".message.assistant:last-child", "07a_result_detail")

        msgs = get_chat_messages(page)
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"
                          and not m.get("isIntermediate")]
        last = assistant_msgs[-1]["text"] if assistant_msgs else ""
        assert len(last) > 80, f"Response too short: {last[:100]}"

    # ── Act 3: Trends — "How do claims evolve over time?" ────────────

    def test_03_monthly_trends(self, page: Page, web_server):
        """Act 3: Monthly claim trends with line charts."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(1000)

        if page.locator("#sources-list .source-card").count() == 0:
            pytest.skip("Source not connected — run test_00 first")

        page.locator("#mode-select").select_option("simple")

        question = (
            "Plot the monthly trend of insurance claims over time: "
            "create one chart showing claim count per month as a line chart, "
            "and a second chart showing the average claim cost per month. "
            "Use clear axis labels and titles."
        )
        page.locator("#question").fill(question)
        _shot(page, "08_act3_question")

        page.locator("#send-btn").click()

        page.wait_for_timeout(8000)
        _shot(page, "09_act3_executing")
        _element_shot(page, "#monitor", "09a_monitor")

        page.locator("#send-btn").wait_for(state="visible", timeout=180_000)

        _shot(page, "10_act3_result")

        # Capture individual charts
        charts = page.locator(".message.assistant:last-child .chart-artifact img")
        if charts.count() > 0:
            _shot(page, "11_act3_charts")
            for i in range(min(charts.count(), 4)):
                chart_path = OUTPUT_DIR / "screenshots" / f"11_trend_chart_{i+1}.png"
                charts.nth(i).screenshot(path=str(chart_path))
        else:
            # Fallback: check for any images
            imgs = page.locator(".message.assistant:last-child img")
            if imgs.count() > 0:
                _shot(page, "11_act3_inline_charts")

        msgs = get_chat_messages(page)
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        last = assistant_msgs[-1]["text"] if assistant_msgs else ""
        assert len(last) > 30, f"Response too short: {last[:100]}"

    # ── Act 4: Cross-analysis — "Car age vs claim cost" ──────────────

    def test_04_age_vs_cost(self, page: Page, web_server):
        """Act 4: Scatter plot of vehicle age vs claim cost by top brands."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(1000)

        if page.locator("#sources-list .source-card").count() == 0:
            pytest.skip("Source not connected — run test_00 first")

        page.locator("#mode-select").select_option("simple")

        question = (
            "Create a scatter plot showing vehicle age (years since manufacture) "
            "on x-axis vs total claim cost on y-axis, colored by car brand "
            "for the top 5 brands. Add a trend line. "
            "Also show a bar chart of average cost by vehicle age group "
            "(0-3 years, 4-7 years, 8-12 years, 13+ years)."
        )
        page.locator("#question").fill(question)
        _shot(page, "12_act4_question")

        page.locator("#send-btn").click()

        page.wait_for_timeout(5000)
        _shot(page, "13_act4_processing")

        page.wait_for_timeout(10000)
        _element_shot(page, "#monitor", "13a_monitor_mid")

        page.locator("#send-btn").wait_for(state="visible", timeout=240_000)

        _shot(page, "14_act4_result")

        # Capture charts
        charts = page.locator(".message.assistant:last-child .chart-artifact img")
        if charts.count() > 0:
            _shot(page, "15_act4_charts")
            for i in range(min(charts.count(), 4)):
                chart_path = OUTPUT_DIR / "screenshots" / f"15_scatter_chart_{i+1}.png"
                charts.nth(i).screenshot(path=str(chart_path))
        else:
            imgs = page.locator(".message.assistant:last-child img")
            if imgs.count() > 0:
                _shot(page, "15_act4_inline_charts")

        _element_shot(page, "#monitor", "14a_monitor_complete")

        msgs = get_chat_messages(page)
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        last = assistant_msgs[-1]["text"] if assistant_msgs else ""
        assert len(last) > 50, f"Response too short: {last[:100]}"

    # ── Act 5: EDA — "Give me the full picture" ──────────────────────

    def test_05_eda_claims(self, page: Page, web_server):
        """Act 5: Extended EDA — cost drivers, patterns, anomalies."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(1000)

        if page.locator("#sources-list .source-card").count() == 0:
            pytest.skip("Source not connected — run test_00 first")

        page.locator("#mode-select").select_option("extended")

        question = (
            "Perform a short EDA of the insurance claims data. Focus on: "
            "1) Cost distribution and outliers, "
            "2) Filing delay patterns (time between damage and claim filing), "
            "3) Seasonal effects on claim frequency and cost, "
            "4) Top factors that drive high-cost claims. "
            "Include charts for each finding."
        )
        page.locator("#question").fill(question)
        _shot(page, "16_act5_question")

        page.locator("#send-btn").click()

        # Capture monitor at various stages of extended execution
        page.wait_for_timeout(5000)
        _shot(page, "17_act5_classifying")

        page.wait_for_timeout(15000)
        _shot(page, "18_act5_planning")
        _element_shot(page, "#monitor", "18a_monitor_plan")

        page.wait_for_timeout(30000)
        _shot(page, "19_act5_mid_analysis")
        _element_shot(page, "#monitor", "19a_monitor_mid")

        # Extended mode may take several minutes
        page.locator("#send-btn").wait_for(state="visible", timeout=600_000)

        _shot(page, "20_act5_result")
        _element_shot(page, "#monitor", "20a_monitor_complete")

        # Capture all charts
        charts = page.locator(".message.assistant:last-child .chart-artifact img")
        if charts.count() > 0:
            _shot(page, "21_act5_charts")
            for i in range(min(charts.count(), 8)):
                chart_path = OUTPUT_DIR / "screenshots" / f"21_eda_chart_{i+1}.png"
                charts.nth(i).screenshot(path=str(chart_path))

        # Verify thorough response
        msgs = get_chat_messages(page)
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        last = assistant_msgs[-1]["text"] if assistant_msgs else ""
        assert len(last) > 200, f"EDA response too short: {last[:100]}"

        # Scroll back to top for final overview
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)
        _shot(page, "22_final_overview")

    # ── Epilogue: Copy videos ────────────────────────────────────────

    def test_06_copy_videos(self, page: Page, web_server):
        """Copy recorded videos to output directory."""
        video_src = Path(__file__).parent / "artifacts" / "videos"
        if not video_src.exists():
            pytest.skip("No videos recorded")

        videos = list(video_src.glob("*.webm"))
        if not videos:
            pytest.skip("No video files found")

        video_dest = OUTPUT_DIR / "videos"
        video_dest.mkdir(exist_ok=True)

        names = [
            "00_connect",
            "01_orientation",
            "02_brand_claims",
            "03_monthly_trends",
            "04_age_vs_cost",
            "05_eda_claims",
            "06_copy",
        ]

        for i, v in enumerate(sorted(videos, key=lambda p: p.stat().st_mtime)):
            name = names[i] if i < len(names) else f"session_{i+1}"
            dest = video_dest / f"{name}.webm"
            shutil.copy2(v, dest)

        copied = list(video_dest.glob("*.webm"))
        assert len(copied) > 0, "No videos copied"
