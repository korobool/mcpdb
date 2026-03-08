"""Web QA tests for export functionality (HTML, PDF, Notebook).

Tests the full export flow: run a query, verify export buttons appear,
click each export button, and verify the output.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .helpers import (
    connect_database,
    submit_query,
    get_chat_messages,
    take_screenshot,
    wait_for_websocket_connected,
)

DB_URL = "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins"


@pytest.fixture
def ready_page(page: Page, web_server):
    """Page with database connected and one query completed."""
    page.goto(web_server)
    wait_for_websocket_connected(page)
    page.wait_for_timeout(500)
    connect_database(page, DB_URL)
    page.wait_for_timeout(1000)
    return page


class TestExportVisibility:
    """Export section should appear only after a query completes."""

    def test_export_hidden_before_query(self, page: Page, web_server, artifact_dir):
        """Export section should be hidden when no queries have been run."""
        page.goto(web_server)
        wait_for_websocket_connected(page)
        page.wait_for_timeout(500)
        connect_database(page, DB_URL)
        page.wait_for_timeout(1000)

        export_section = page.locator("#export-section")
        expect(export_section).to_be_hidden()

        take_screenshot(page, "export_hidden_before_query", artifact_dir)

    def test_export_visible_after_query(self, ready_page: Page, artifact_dir):
        """Export section should appear after a query completes."""
        page = ready_page
        submit_query(page, "How many tables are in the database?", mode="quick", timeout=90_000)

        export_section = page.locator("#export-section")
        expect(export_section).to_be_visible()

        # All 4 buttons should be visible
        buttons = export_section.locator(".btn")
        assert buttons.count() == 4  # HTML, PDF, Notebook, Open in Jupyter

        take_screenshot(page, "export_visible_after_query", artifact_dir)

    def test_export_hidden_after_new_conversation(self, ready_page: Page, artifact_dir):
        """Export section should hide after clicking New Conversation."""
        page = ready_page
        submit_query(page, "How many tables?", mode="quick", timeout=90_000)

        # Verify visible first
        expect(page.locator("#export-section")).to_be_visible()

        # Click new conversation
        page.locator("text=New conversation").click()
        page.wait_for_timeout(500)

        # Should be hidden again
        expect(page.locator("#export-section")).to_be_hidden()

        take_screenshot(page, "export_hidden_after_new_convo", artifact_dir)


class TestHTMLExport:
    """Test HTML export opens in a new tab."""

    def test_html_export_opens_tab(self, ready_page: Page, artifact_dir):
        """Clicking HTML export should generate a report viewable in a new tab."""
        page = ready_page
        result = submit_query(
            page, "What are the top 5 car brands by claim count?",
            mode="simple", timeout=120_000,
        )
        assert not result["error"]

        take_screenshot(page, "export_html_before_click", artifact_dir)

        # Intercept window.open to capture the URL (avoids popup blocker issues)
        page.evaluate("""
            window.__exportUrl = null;
            window.__origOpen = window.open;
            window.open = function(url, target) { window.__exportUrl = url; return null; };
        """)

        page.locator("#export-section .btn", has_text="HTML").click()

        # Wait for the export URL to be set by the async exportHTML function
        page.wait_for_function("window.__exportUrl !== null", timeout=30_000)
        export_url = page.evaluate("window.__exportUrl")
        assert "/api/export/view/" in export_url

        # Open the report URL in a new page
        new_page = page.context.new_page()
        base_url = page.evaluate("window.location.origin")
        new_page.goto(f"{base_url}{export_url}")
        new_page.wait_for_load_state("domcontentloaded")

        # Verify the HTML report content
        body_text = new_page.locator("body").inner_text()
        assert "MCPDB" in body_text
        assert "car brands" in body_text.lower() or "top 5" in body_text.lower() or len(body_text) > 100

        # Verify it's a self-contained report (has styling)
        html = new_page.content()
        assert "<style>" in html

        take_screenshot(page, "export_html_after_click", artifact_dir)
        new_page.screenshot(path=str(artifact_dir / "screenshots" / "export_html_report.png"), full_page=True)
        new_page.close()

        # Restore window.open
        page.evaluate("window.open = window.__origOpen;")


class TestNotebookExport:
    """Test Jupyter notebook export."""

    def test_notebook_download(self, ready_page: Page, artifact_dir):
        """Notebook should have connection string, SQL code cells, and proper structure."""
        page = ready_page
        result = submit_query(
            page, "How many rows are in the ins_cars table?",
            mode="simple", timeout=120_000,
        )
        assert not result["error"]

        # Listen for download
        with page.expect_download() as download_info:
            page.locator("#export-section .btn", has_text="Notebook").click()

        download = download_info.value
        assert download.suggested_filename.endswith(".ipynb")

        # Save and verify content
        dest = artifact_dir / "downloads" / download.suggested_filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(dest))

        import json
        with open(dest) as f:
            nb = json.load(f)

        assert "cells" in nb
        assert nb["metadata"]["kernelspec"]["name"] == "python3"

        def _src(cell): return "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
        all_sources = " ".join(_src(c) for c in nb["cells"])

        # Connection string must be populated with actual credentials
        assert 'CONNECTION_STRING = ""' not in all_sources, "CONNECTION_STRING is empty in notebook!"
        assert "dbtalk" in all_sources or "localhost" in all_sources, \
            f"Connection string not populated. Setup cell: {_src(nb['cells'][1])[:200]}"

        # Must have executable code cells with SQL (not just markdown responses)
        code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
        assert len(code_cells) >= 2, f"Expected at least 2 code cells (setup + query), got {len(code_cells)}"

        # At least one code cell should contain db_query (actual SQL execution)
        sql_cells = [c for c in code_cells if "db_query" in _src(c) and "def db_query" not in _src(c)]
        assert len(sql_cells) >= 1, \
            f"No SQL query code cells found. Code cells: {[_src(c)[:100] for c in code_cells]}"

        take_screenshot(page, "export_notebook_done", artifact_dir)


class TestMultiTurnExport:
    """Test export with multiple conversation turns."""

    def test_multi_turn_html_export(self, ready_page: Page, artifact_dir):
        """HTML export should include all conversation turns."""
        page = ready_page

        # Run two queries
        submit_query(page, "How many tables are there?", mode="quick", timeout=90_000)
        submit_query(page, "What are the column names in ins_cars?", mode="quick", timeout=90_000)

        # Intercept window.open to capture URL
        page.evaluate("""
            window.__exportUrl = null;
            window.__origOpen = window.open;
            window.open = function(url, target) { window.__exportUrl = url; return null; };
        """)

        page.locator("#export-section .btn", has_text="HTML").click()
        page.wait_for_function("window.__exportUrl !== null", timeout=30_000)
        export_url = page.evaluate("window.__exportUrl")

        new_page = page.context.new_page()
        base_url = page.evaluate("window.location.origin")
        new_page.goto(f"{base_url}{export_url}")
        new_page.wait_for_load_state("domcontentloaded")

        body_text = new_page.locator("body").inner_text()
        # Both questions should be in the report
        assert "tables" in body_text.lower()
        assert "ins_cars" in body_text.lower() or "column" in body_text.lower()

        new_page.screenshot(
            path=str(artifact_dir / "screenshots" / "export_multi_turn_report.png"),
            full_page=True,
        )
        new_page.close()
        page.evaluate("window.open = window.__origOpen;")

        take_screenshot(page, "export_multi_turn_done", artifact_dir)

    def test_multi_turn_notebook_has_all_turns(self, ready_page: Page, artifact_dir):
        """Notebook should have cells for all turns."""
        page = ready_page

        submit_query(page, "How many rows in ins_damages?", mode="quick", timeout=90_000)
        submit_query(page, "Show top 3 damage types", mode="quick", timeout=90_000)

        with page.expect_download() as download_info:
            page.locator("#export-section .btn", has_text="Notebook").click()

        download = download_info.value
        dest = artifact_dir / "downloads" / download.suggested_filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(dest))

        import json
        with open(dest) as f:
            nb = json.load(f)

        # Should have turn headers for both queries
        def _src(cell): return "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
        md_cells = [c for c in nb["cells"] if c["cell_type"] == "markdown"]
        turn_cells = [c for c in md_cells if "## Turn" in _src(c)]
        assert len(turn_cells) >= 2

        take_screenshot(page, "export_multi_turn_notebook", artifact_dir)


class TestExportWithCharts:
    """Test export preserves chart artifacts."""

    def test_chart_in_html_export(self, ready_page: Page, artifact_dir):
        """Charts should appear as images in HTML export."""
        page = ready_page
        result = submit_query(
            page,
            "Create a bar chart showing the top 5 car brands by number of claims",
            mode="simple",
            timeout=180_000,
        )
        assert not result["error"]

        # Check if charts were generated
        charts_in_page = page.locator(".message.assistant:last-child .chart-artifact img")
        has_charts = charts_in_page.count() > 0

        take_screenshot(page, "export_chart_query_result", artifact_dir)

        # Intercept window.open to capture URL
        page.evaluate("""
            window.__exportUrl = null;
            window.__origOpen = window.open;
            window.open = function(url, target) { window.__exportUrl = url; return null; };
        """)

        page.locator("#export-section .btn", has_text="HTML").click()
        page.wait_for_function("window.__exportUrl !== null", timeout=30_000)
        export_url = page.evaluate("window.__exportUrl")

        new_page = page.context.new_page()
        base_url = page.evaluate("window.location.origin")
        new_page.goto(f"{base_url}{export_url}")
        new_page.wait_for_load_state("domcontentloaded")

        if has_charts:
            # Report should have chart images
            report_imgs = new_page.locator("img")
            assert report_imgs.count() > 0

        new_page.screenshot(
            path=str(artifact_dir / "screenshots" / "export_chart_report.png"),
            full_page=True,
        )
        new_page.close()
        page.evaluate("window.open = window.__origOpen;")

        take_screenshot(page, "export_chart_done", artifact_dir)
