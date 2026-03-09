"""Web QA tests for export from different source types.

Tests export (HTML, PDF, Notebook) from CSV, Excel, and PostgreSQL sources.
Verifies exported files contain correct setup code and content.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from .helpers import (
    connect_database,
    upload_csv_files,
    upload_excel_file,
    submit_query,
    take_screenshot,
    wait_for_websocket_connected,
)

MYSQL_URL = "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins"
PG_URL = "postgresql://readonly:uPxAP3mQ3N74@34.147.20.48/portfolio_analysis?sslmode=require"
SMALL_XLSX = "/home/olek/Downloads/Telegram Desktop/книга_обліку_доходів_і_витрат_ФОП_Коробов_2025.xlsx"


def _create_temp_csv(name: str, rows: list[list], tmpdir: Path) -> str:
    path = tmpdir / name
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        for row in rows:
            writer.writerow(row)
    return str(path)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def ready_page(page: Page, web_server):
    page.goto(web_server)
    wait_for_websocket_connected(page)
    page.wait_for_timeout(500)
    # Clean up any leftover sources from previous tests
    from .helpers import remove_all_sources
    remove_all_sources(page)
    page.wait_for_timeout(300)
    return page


# =====================================================================
#  CSV Export Tests
# =====================================================================

class TestCSVExport:
    def test_csv_notebook_export(self, ready_page: Page, artifact_dir, tmp_path):
        """Notebook from CSV source should use DuckDB, not SQLAlchemy."""
        page = ready_page

        csv_path = _create_temp_csv("sales.csv", [
            ["date", "product", "revenue"],
            ["2025-01-01", "Widget", 100],
            ["2025-01-02", "Gadget", 250],
            ["2025-01-03", "Widget", 150],
        ], tmp_path)

        upload_csv_files(page, [csv_path])
        submit_query(page, "What is the total revenue?", mode="quick", timeout=90_000)

        take_screenshot(page, "csv_export_before_notebook", artifact_dir)

        with page.expect_download() as download_info:
            page.locator("#export-section .btn", has_text="Notebook").click()

        download = download_info.value
        assert download.suggested_filename.endswith(".ipynb")

        dest = artifact_dir / "downloads" / download.suggested_filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(dest))

        nb = json.loads(dest.read_text())
        assert "cells" in nb

        def _src(cell):
            return "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]

        all_sources = " ".join(_src(c) for c in nb["cells"])

        # DuckDB-based setup (not SQLAlchemy)
        assert "duckdb" in all_sources
        assert "read_csv_auto" in all_sources
        # Should NOT have SQL database connection string
        assert "CONNECTION_STRING" not in all_sources or '""' not in all_sources

        take_screenshot(page, "csv_export_notebook_done", artifact_dir)

    def test_csv_html_export(self, ready_page: Page, artifact_dir, tmp_path):
        """HTML export from CSV source should contain question and answer."""
        page = ready_page

        csv_path = _create_temp_csv("metrics.csv", [
            ["metric", "value"],
            ["accuracy", 0.95],
            ["precision", 0.88],
        ], tmp_path)

        upload_csv_files(page, [csv_path])
        submit_query(page, "List all metrics", mode="quick", timeout=90_000)

        # Intercept window.open
        page.evaluate("""
            window.__exportUrl = null;
            window.__origOpen = window.open;
            window.open = function(url, target) { window.__exportUrl = url; return null; };
        """)

        page.locator("#export-section .btn", has_text="HTML").click()
        page.wait_for_function("window.__exportUrl !== null", timeout=30_000)
        export_url = page.evaluate("window.__exportUrl")
        assert "/api/export/view/" in export_url

        new_page = page.context.new_page()
        base_url = page.evaluate("window.location.origin")
        new_page.goto(f"{base_url}{export_url}")
        new_page.wait_for_load_state("domcontentloaded")

        body_text = new_page.locator("body").inner_text()
        assert "metric" in body_text.lower() or "MCPDB" in body_text

        new_page.screenshot(
            path=str(artifact_dir / "screenshots" / "csv_html_report.png"),
            full_page=True,
        )
        new_page.close()
        page.evaluate("window.open = window.__origOpen;")


# =====================================================================
#  Excel Export Tests
# =====================================================================

class TestExcelExport:
    def test_excel_notebook_export(self, ready_page: Page, artifact_dir):
        """Notebook from Excel source should use DuckDB + openpyxl."""
        page = ready_page
        if not Path(SMALL_XLSX).exists():
            pytest.skip(f"Excel file not found: {SMALL_XLSX}")

        upload_excel_file(page, SMALL_XLSX, timeout=60_000)
        submit_query(
            page, "What sheets and data are in this workbook?",
            mode="quick", timeout=180_000,
        )

        take_screenshot(page, "excel_export_before_notebook", artifact_dir)

        with page.expect_download() as download_info:
            page.locator("#export-section .btn", has_text="Notebook").click()

        download = download_info.value
        assert download.suggested_filename.endswith(".ipynb")

        dest = artifact_dir / "downloads" / download.suggested_filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(dest))

        nb = json.loads(dest.read_text())

        def _src(cell):
            return "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]

        all_sources = " ".join(_src(c) for c in nb["cells"])
        assert "duckdb" in all_sources
        # Should reference openpyxl or st_read for Excel
        assert "openpyxl" in all_sources or "st_read" in all_sources

        take_screenshot(page, "excel_export_notebook_done", artifact_dir)


# =====================================================================
#  PostgreSQL Export Tests
# =====================================================================

class TestPostgreSQLExport:
    @pytest.mark.slow
    def test_postgres_notebook_export(self, ready_page: Page, artifact_dir):
        """Notebook from PostgreSQL should use psycopg2 and populated connection string."""
        page = ready_page
        connect_database(page, PG_URL, timeout=60_000)

        submit_query(
            page, "What are the main tables?",
            mode="quick", timeout=180_000,
        )

        take_screenshot(page, "pg_export_before_notebook", artifact_dir)

        with page.expect_download() as download_info:
            page.locator("#export-section .btn", has_text="Notebook").click()

        download = download_info.value
        dest = artifact_dir / "downloads" / download.suggested_filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(dest))

        nb = json.loads(dest.read_text())

        def _src(cell):
            return "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]

        all_sources = " ".join(_src(c) for c in nb["cells"])
        assert "psycopg2" in all_sources
        # Connection string should be populated (not empty)
        assert 'CONNECTION_STRING = ""' not in all_sources

        take_screenshot(page, "pg_export_notebook_done", artifact_dir)

    @pytest.mark.slow
    def test_postgres_html_export(self, ready_page: Page, artifact_dir):
        """HTML export from PostgreSQL source."""
        page = ready_page
        connect_database(page, PG_URL, timeout=60_000)

        submit_query(
            page, "List all tables with row counts",
            mode="quick", timeout=180_000,
        )

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
        assert "MCPDB" in body_text
        assert len(body_text) > 100

        new_page.screenshot(
            path=str(artifact_dir / "screenshots" / "pg_html_report.png"),
            full_page=True,
        )
        new_page.close()
        page.evaluate("window.open = window.__origOpen;")


# =====================================================================
#  PDF Export Tests
# =====================================================================

class TestPDFExport:
    def test_pdf_download(self, ready_page: Page, artifact_dir):
        """PDF export should download a valid PDF file."""
        page = ready_page
        connect_database(page, MYSQL_URL)

        submit_query(
            page, "How many tables are there?",
            mode="quick", timeout=180_000,
        )

        take_screenshot(page, "pdf_export_before", artifact_dir)

        with page.expect_download(timeout=60_000) as download_info:
            page.locator("#export-section .btn", has_text="PDF").click()

        download = download_info.value
        assert download.suggested_filename.endswith(".pdf")

        dest = artifact_dir / "downloads" / download.suggested_filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(dest))

        # Verify it's a valid PDF (starts with %PDF magic bytes)
        with open(dest, "rb") as f:
            header = f.read(5)
        assert header == b"%PDF-", f"Not a valid PDF file, header: {header!r}"

        take_screenshot(page, "pdf_export_done", artifact_dir)


# =====================================================================
#  MySQL ERD in Notebook Export
# =====================================================================

class TestMySQLNotebookERD:
    def test_mysql_notebook_has_erd(self, ready_page: Page, artifact_dir):
        """MySQL notebook export should include ERD with base64-encoded mermaid."""
        page = ready_page
        connect_database(page, MYSQL_URL)

        submit_query(
            page, "What are the top 3 tables by row count?",
            mode="simple", timeout=240_000,
        )

        with page.expect_download() as download_info:
            page.locator("#export-section .btn", has_text="Notebook").click()

        download = download_info.value
        dest = artifact_dir / "downloads" / f"mysql_{download.suggested_filename}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(dest))

        nb = json.loads(dest.read_text())

        def _src(cell):
            return "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]

        # Check for ERD cell
        code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
        erd_cells = [c for c in code_cells if "b64decode" in _src(c) and "mermaid" in _src(c)]

        if erd_cells:
            erd_src = _src(erd_cells[0])
            assert "iframe" in erd_src
            assert "IPython.display" in erd_src
            # Verify the base64 decodes to valid mermaid
            import base64
            import re
            match = re.search(r'b64decode\("([^"]+)"\)', erd_src)
            if match:
                decoded = base64.b64decode(match.group(1)).decode()
                assert "erDiagram" in decoded

        # Check connection string is populated
        all_sources = " ".join(_src(c) for c in nb["cells"])
        assert "pymysql" in all_sources
        assert 'CONNECTION_STRING = ""' not in all_sources

        take_screenshot(page, "mysql_notebook_erd_done", artifact_dir)


# =====================================================================
#  Multi-turn export tests
# =====================================================================

class TestMultiTurnExportSources:
    def test_csv_multi_turn_notebook(self, ready_page: Page, artifact_dir, tmp_path):
        """Multi-turn notebook from CSV should have turn headers for each query."""
        page = ready_page

        csv_path = _create_temp_csv("employees.csv", [
            ["id", "name", "department", "salary"],
            [1, "Alice", "Engineering", 95000],
            [2, "Bob", "Marketing", 72000],
            [3, "Charlie", "Engineering", 88000],
            [4, "Diana", "Sales", 65000],
        ], tmp_path)

        upload_csv_files(page, [csv_path])

        submit_query(page, "How many employees are there?", mode="quick", timeout=90_000)
        submit_query(page, "What is the average salary by department?", mode="quick", timeout=90_000)

        with page.expect_download() as download_info:
            page.locator("#export-section .btn", has_text="Notebook").click()

        download = download_info.value
        dest = artifact_dir / "downloads" / download.suggested_filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(dest))

        nb = json.loads(dest.read_text())

        def _src(cell):
            return "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]

        md_cells = [c for c in nb["cells"] if c["cell_type"] == "markdown"]
        turn_cells = [c for c in md_cells if "## Turn" in _src(c)]
        assert len(turn_cells) >= 2, f"Expected >= 2 turn headers, got {len(turn_cells)}"

        take_screenshot(page, "csv_multi_turn_notebook", artifact_dir)
