"""Web QA tests for source connections (Database, CSV, Excel).

Tests the full connection flow: connect a source, verify it appears,
run a query against it, and verify the result.
"""
from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from .helpers import (
    connect_database,
    upload_csv_files,
    upload_excel_file,
    submit_query,
    get_source_count,
    get_source_names,
    remove_all_sources,
    take_screenshot,
    wait_for_websocket_connected,
)


# ── Database source paths ────────────────────────────────────────────

MYSQL_URL = "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins"
PG_URL = "postgresql://readonly:uPxAP3mQ3N74@34.147.20.48/portfolio_analysis?sslmode=require"

# Real file paths (only used in @pytest.mark.slow tests)
PAID_XLSX = "/home/olek/Downloads/Telegram Desktop/Paid.xlsx"
LATENCY_XLSX = "/home/olek/Downloads/Telegram Desktop/inference_latency_results.xlsx"
SMALL_XLSX = "/home/olek/Downloads/Telegram Desktop/книга_обліку_доходів_і_витрат_ФОП_Коробов_2025.xlsx"
LARGE_CSV = "/home/olek/Downloads/Qala-MTPL-V4.csv"


# ── Helper to create temp CSV files ──────────────────────────────────

def _create_temp_csv(name: str, rows: list[list], tmpdir: Path) -> str:
    """Create a temp CSV file with headers + data rows."""
    path = tmpdir / name
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        for row in rows:
            writer.writerow(row)
    return str(path)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def ready_page(page: Page, web_server):
    """Page with WebSocket connected and no sources."""
    page.goto(web_server)
    wait_for_websocket_connected(page)
    page.wait_for_timeout(500)
    # Clean up any leftover sources from previous tests
    remove_all_sources(page)
    page.wait_for_timeout(300)
    return page


# =====================================================================
#  MySQL connection tests
# =====================================================================

class TestMySQLConnection:
    def test_mysql_connect_and_query(self, ready_page: Page, artifact_dir):
        page = ready_page
        connect_database(page, MYSQL_URL)
        assert get_source_count(page) == 1

        take_screenshot(page, "mysql_connected", artifact_dir)

        result = submit_query(
            page, "How many tables are in the database?",
            mode="quick", timeout=90_000,
        )
        assert not result["error"]
        assert "21" in result["response"] or "table" in result["response"].lower()

        take_screenshot(page, "mysql_quick_query_result", artifact_dir)

    def test_mysql_simple_mode(self, ready_page: Page, artifact_dir):
        page = ready_page
        connect_database(page, MYSQL_URL)

        result = submit_query(
            page, "What are the top 5 car brands by number of claims?",
            mode="simple", timeout=120_000,
        )
        assert not result["error"]
        assert len(result["response"]) > 50

        take_screenshot(page, "mysql_simple_result", artifact_dir)


# =====================================================================
#  PostgreSQL connection tests
# =====================================================================

class TestPostgreSQLConnection:
    @pytest.mark.slow
    def test_postgres_connect_and_query(self, ready_page: Page, artifact_dir):
        page = ready_page
        connect_database(page, PG_URL, timeout=60_000)
        assert get_source_count(page) == 1

        take_screenshot(page, "postgres_connected", artifact_dir)

        result = submit_query(
            page, "How many tables are in the database?",
            mode="quick", timeout=90_000,
        )
        assert not result["error"]

        take_screenshot(page, "postgres_quick_result", artifact_dir)

    @pytest.mark.slow
    def test_postgres_simple_mode(self, ready_page: Page, artifact_dir):
        page = ready_page
        connect_database(page, PG_URL, timeout=60_000)

        result = submit_query(
            page, "List all tables with their row counts",
            mode="simple", timeout=240_000,
        )
        assert not result["error"]
        assert len(result["response"]) > 30

        take_screenshot(page, "postgres_simple_result", artifact_dir)


# =====================================================================
#  CSV upload tests
# =====================================================================

class TestCSVUpload:
    def test_csv_upload_and_query(self, ready_page: Page, artifact_dir, tmp_path):
        page = ready_page

        # Create a small temp CSV
        csv_path = _create_temp_csv("orders.csv", [
            ["order_id", "customer", "amount", "date"],
            [1, "Alice", 100.50, "2025-01-15"],
            [2, "Bob", 250.00, "2025-01-16"],
            [3, "Charlie", 75.25, "2025-01-17"],
            [4, "Alice", 180.00, "2025-02-01"],
            [5, "Bob", 320.75, "2025-02-05"],
        ], tmp_path)

        upload_csv_files(page, [csv_path])
        assert get_source_count(page) == 1

        take_screenshot(page, "csv_uploaded", artifact_dir)

        result = submit_query(
            page, "How many orders are there?",
            mode="quick", timeout=90_000,
        )
        assert not result["error"]

        take_screenshot(page, "csv_query_result", artifact_dir)

    def test_csv_multi_file_upload(self, ready_page: Page, artifact_dir, tmp_path):
        page = ready_page

        csv1 = _create_temp_csv("products.csv", [
            ["product_id", "name", "price"],
            [1, "Widget", 9.99],
            [2, "Gadget", 24.50],
        ], tmp_path)
        csv2 = _create_temp_csv("categories.csv", [
            ["cat_id", "category_name"],
            [1, "Electronics"],
            [2, "Hardware"],
        ], tmp_path)

        upload_csv_files(page, [csv1, csv2])
        assert get_source_count(page) == 1

        take_screenshot(page, "csv_multi_uploaded", artifact_dir)

        result = submit_query(
            page, "What tables do I have?",
            mode="quick", timeout=90_000,
        )
        assert not result["error"]

        take_screenshot(page, "csv_multi_query", artifact_dir)

    @pytest.mark.slow
    def test_large_csv_upload(self, ready_page: Page, artifact_dir):
        """Upload real 79MB CSV and query it."""
        page = ready_page
        csv_path = LARGE_CSV
        if not Path(csv_path).exists():
            pytest.skip(f"Large CSV not found: {csv_path}")

        upload_csv_files(page, [csv_path], timeout=120_000)
        assert get_source_count(page) == 1

        take_screenshot(page, "large_csv_uploaded", artifact_dir)

        result = submit_query(
            page, "How many rows and columns are in this data? List column names.",
            mode="quick", timeout=120_000,
        )
        assert not result["error"]

        take_screenshot(page, "large_csv_query_result", artifact_dir)


# =====================================================================
#  Excel upload tests
# =====================================================================

class TestExcelUpload:
    def test_excel_upload_small(self, ready_page: Page, artifact_dir):
        """Upload the smallest real Excel file (25KB)."""
        page = ready_page
        if not Path(SMALL_XLSX).exists():
            pytest.skip(f"Excel file not found: {SMALL_XLSX}")

        upload_excel_file(page, SMALL_XLSX, timeout=60_000)
        assert get_source_count(page) == 1

        take_screenshot(page, "excel_small_uploaded", artifact_dir)

        result = submit_query(
            page, "Describe the structure and contents of this workbook",
            mode="quick", timeout=90_000,
        )
        assert not result["error"]

        take_screenshot(page, "excel_small_query", artifact_dir)

    @pytest.mark.slow
    def test_excel_upload_paid(self, ready_page: Page, artifact_dir):
        """Upload Paid.xlsx (2.1MB) and query it."""
        page = ready_page
        if not Path(PAID_XLSX).exists():
            pytest.skip(f"Excel file not found: {PAID_XLSX}")

        upload_excel_file(page, PAID_XLSX, timeout=60_000)
        assert get_source_count(page) == 1

        take_screenshot(page, "excel_paid_uploaded", artifact_dir)

        result = submit_query(
            page, "How many rows are there? What are the column names?",
            mode="quick", timeout=90_000,
        )
        assert not result["error"]

        take_screenshot(page, "excel_paid_query", artifact_dir)

    @pytest.mark.slow
    def test_excel_upload_latency(self, ready_page: Page, artifact_dir):
        """Upload inference_latency_results.xlsx (3.4MB)."""
        page = ready_page
        if not Path(LATENCY_XLSX).exists():
            pytest.skip(f"Excel file not found: {LATENCY_XLSX}")

        upload_excel_file(page, LATENCY_XLSX, timeout=60_000)
        assert get_source_count(page) == 1

        take_screenshot(page, "excel_latency_uploaded", artifact_dir)

        result = submit_query(
            page, "What is the average inference latency? Show a summary by model.",
            mode="simple", timeout=120_000,
        )
        assert not result["error"]

        take_screenshot(page, "excel_latency_result", artifact_dir)


# =====================================================================
#  Multi-source tests
# =====================================================================

class TestMultiSource:
    def test_mysql_plus_csv(self, ready_page: Page, artifact_dir, tmp_path):
        """Connect MySQL and upload CSV — both sources should be available."""
        page = ready_page

        # Connect MySQL
        connect_database(page, MYSQL_URL)
        assert get_source_count(page) == 1

        # Upload CSV
        csv_path = _create_temp_csv("regions.csv", [
            ["region_id", "name", "country"],
            [1, "Sofia", "Bulgaria"],
            [2, "Plovdiv", "Bulgaria"],
        ], tmp_path)

        # Open CSV section and upload
        details = page.locator("#csv-details")
        if not details.get_attribute("open"):
            details.locator("summary").click()
            page.wait_for_timeout(300)
        page.locator("#csv-files").set_input_files([csv_path])
        page.wait_for_timeout(500)
        page.locator("#csv-upload-btn").click()

        # Wait for the second source card to appear
        page.locator("#sources-list .source-card:nth-child(2)").wait_for(
            state="visible", timeout=60_000,
        )

        assert get_source_count(page) >= 2

        take_screenshot(page, "multi_source_connected", artifact_dir)

        result = submit_query(
            page, "What data sources do I have connected?",
            mode="quick", timeout=90_000,
        )
        assert not result["error"]

        take_screenshot(page, "multi_source_query", artifact_dir)


# =====================================================================
#  Error handling tests
# =====================================================================

class TestSourceErrors:
    def test_invalid_database_url(self, ready_page: Page, artifact_dir):
        """Connecting to invalid URL should show error, not crash."""
        page = ready_page

        # Fill invalid connection string
        details = page.locator("#connect-details")
        if not details.get_attribute("open"):
            details.locator("summary").click()

        page.locator("#conn-str").fill("mysql+pymysql://invalid:invalid@localhost:9999/nonexistent")
        page.locator("#connect-details .btn-primary").click()

        # Wait for error alert or notification
        page.wait_for_timeout(5000)

        # Should still have 0 sources (connection failed)
        assert get_source_count(page) == 0

        take_screenshot(page, "invalid_db_error", artifact_dir)
