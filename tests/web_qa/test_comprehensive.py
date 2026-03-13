"""Comprehensive web QA: hundreds of queries across all source types.

Tests MySQL, PostgreSQL, CSV, and Excel sources with quality validation.
Run with: pytest tests/web_qa/test_comprehensive.py --headed --record-video -v -s

This test file is designed for long interactive sessions (2-4 hours).
"""
from __future__ import annotations

import base64
import csv
import json
import re
import time
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from .helpers import (
    connect_database,
    upload_csv_files,
    upload_excel_file,
    submit_query,
    get_source_count,
    remove_all_sources,
    take_screenshot,
    wait_for_websocket_connected,
    get_last_response,
    get_tables_in_response,
)

# ── Source paths ──────────────────────────────────────────────────────

MYSQL_URL = "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins"
PG_URL = "postgresql://readonly:uPxAP3mQ3N74@34.147.20.48/portfolio_analysis?sslmode=require"

PAID_XLSX = "/home/olek/Downloads/Telegram Desktop/Paid.xlsx"
LATENCY_XLSX = "/home/olek/Downloads/Telegram Desktop/inference_latency_results.xlsx"
SMALL_XLSX = "/home/olek/Downloads/Telegram Desktop/книга_обліку_доходів_і_витрат_ФОП_Коробов_2025.xlsx"
CALC_XLSX = "/home/olek/Downloads/Telegram Desktop/расчет_2025_коробов.xlsx"
LARGE_CSV = "/home/olek/Downloads/Qala-MTPL-V4.csv"
CLAIMS_CSV = "/home/olek/workspace/prima_etl_agent/temp/input/CLAIMS.csv"


# ── Quality validation ────────────────────────────────────────────────

class QualityReport:
    """Track query quality across the session."""

    def __init__(self, artifact_dir: Path):
        self.results: list[dict] = []
        self.artifact_dir = artifact_dir

    def record(self, source: str, question: str, result: dict, checks: dict):
        entry = {
            "source": source,
            "question": question,
            "mode": result.get("mode", ""),
            "elapsed": result.get("elapsed", 0),
            "error": result.get("error", False),
            "has_charts": result.get("has_charts", False),
            "followup_count": result.get("followup_count", 0),
            "response_length": len(result.get("response", "")),
            "checks": checks,
            "passed": all(checks.values()),
        }
        self.results.append(entry)
        status = "PASS" if entry["passed"] else "FAIL"
        failed = [k for k, v in checks.items() if not v]
        print(f"  [{status}] {source} | {question[:60]}... | {entry['elapsed']:.1f}s | {', '.join(failed) if failed else 'OK'}")

    def save(self):
        report_path = self.artifact_dir / "quality_report.json"
        with open(report_path, "w") as f:
            json.dump(self.results, f, indent=2)

        total = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        failed = total - passed
        errors = sum(1 for r in self.results if r["error"])

        summary = (
            f"\n{'=' * 70}\n"
            f"  QUALITY REPORT: {passed}/{total} passed, {failed} failed, {errors} errors\n"
            f"{'=' * 70}\n"
        )
        if failed > 0:
            summary += "\nFailed queries:\n"
            for r in self.results:
                if not r["passed"]:
                    failed_checks = [k for k, v in r["checks"].items() if not v]
                    summary += f"  - [{r['source']}] {r['question'][:70]} — {', '.join(failed_checks)}\n"

        print(summary)
        (self.artifact_dir / "quality_summary.txt").write_text(summary)


def _check_response(result: dict, **kwargs) -> dict:
    """Run quality checks on a query result.

    Supported checks:
        no_error=True         — response should not have error
        min_length=N          — response text should be >= N chars
        contains=["word"]     — response should contain these words (case-insensitive)
        has_number=True        — response should contain at least one number
        has_table=True         — response should mention tabular data
        no_empty_response=True — response should not be empty
    """
    response = result.get("response", "")
    resp_lower = response.lower()
    checks = {}

    if kwargs.get("no_error", True):
        checks["no_error"] = not result.get("error", False)

    if kwargs.get("no_empty_response", True):
        checks["no_empty_response"] = len(response.strip()) > 10

    if "min_length" in kwargs:
        checks["min_length"] = len(response) >= kwargs["min_length"]

    if "contains" in kwargs:
        for word in kwargs["contains"]:
            checks[f"contains_{word}"] = word.lower() in resp_lower

    if kwargs.get("has_number"):
        checks["has_number"] = bool(re.search(r"\d+", response))

    if kwargs.get("has_table"):
        checks["has_table"] = "|" in response or "table" in resp_lower or "<table" in resp_lower

    return checks


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def quality(artifact_dir):
    report = QualityReport(artifact_dir)
    yield report
    report.save()


@pytest.fixture
def clean_page(page: Page, web_server):
    """Page with WS connected and all sources removed."""
    page.goto(web_server, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_load_state("load", timeout=30_000)
    wait_for_websocket_connected(page)
    page.wait_for_timeout(500)
    remove_all_sources(page)
    page.wait_for_timeout(300)
    return page


# =====================================================================
#  MySQL: Quick, Simple, Extended modes (bgins insurance DB)
# =====================================================================

class TestMySQLQueries:
    """Run many queries against MySQL bgins database."""

    QUESTIONS_QUICK = [
        ("How many tables are in the database?", {"has_number": True}),
        ("What tables are in the database?", {"min_length": 20}),
        ("Describe the ins_cars table", {"min_length": 20}),
        ("What are the column names in ins_damages?", {"min_length": 20}),
        ("Show the schema of ins_opis table", {"min_length": 20}),
        ("How many columns does ins_cars have?", {"min_length": 10}),
        ("What is the primary key of ins_damages?", {"min_length": 10}),
    ]

    QUESTIONS_SIMPLE = [
        ("How many rows are in the ins_cars table?", {"has_number": True}),
        ("What are the top 5 car brands by number of records?", {"has_number": True, "min_length": 50}),
        ("How many distinct car makes are there?", {"has_number": True}),
        ("What is the average claim cost in the ins_damages table?", {"has_number": True}),
        ("Show the distribution of car years — how many cars per year?", {"has_number": True}),
        ("What are the most common damage types?", {"min_length": 50}),
        ("How many claims were filed per month? Show the trend.", {"has_number": True}),
        ("What is the total number of claims and total cost?", {"has_number": True}),
        ("Which car brand has the highest average claim cost?", {"has_number": True}),
        ("Show the top 10 most expensive individual claims", {"has_number": True, "min_length": 50}),
        ("How many cars have more than one claim?", {"has_number": True}),
        ("What percentage of cars have zero claims?", {"has_number": True}),
        ("List the foreign key relationships between tables", {"min_length": 30}),
        ("Show the count of records in every table", {"has_number": True}),
        ("What is the date range of claims in the database?", {"has_number": True}),
    ]

    QUESTIONS_CHARTS = [
        ("Create a bar chart of top 10 car brands by claim count", {"min_length": 30}),
        ("Plot the monthly trend of claims over time", {"min_length": 30}),
        ("Create a pie chart showing damage type distribution", {"min_length": 30}),
    ]

    def _ensure_mysql(self, page: Page):
        """Ensure MySQL is connected, fresh conversation."""
        remove_all_sources(page)
        page.wait_for_timeout(300)
        connect_database(page, MYSQL_URL)

    @pytest.fixture(autouse=True)
    def _setup(self, clean_page: Page, artifact_dir):
        self.page = clean_page
        self.artifact_dir = artifact_dir

    def _safe_query(self, question, quality, source, mode="simple", timeout=240_000, checks_kwargs=None):
        """Submit query with timeout recovery. Reconnects MySQL after failures."""
        try:
            result = submit_query(self.page, question, mode=mode, timeout=timeout)
        except Exception:
            quality.record(source, question, {"response": "", "error": True}, {"no_timeout": False})
            self._recover_and_reconnect()
            return None
        # Check if the response itself is an error — reconnect if so
        if result.get("error"):
            quality.record(source, question, result, {"no_error": False})
            self._recover_and_reconnect()
            return result
        checks = _check_response(result, **(checks_kwargs or {}))
        quality.record(source, question, result, checks)
        slug = question[:30].replace(' ', '_').replace('?', '')
        take_screenshot(self.page, f"{source}_{slug}", self.artifact_dir)
        return result

    def _recover_and_reconnect(self):
        """Recover UI state and reconnect MySQL after timeout/error."""
        try:
            self.page.locator("text=New conversation").click()
            self.page.wait_for_timeout(500)
            self.page.wait_for_function("() => typeof isQuerying !== 'undefined' && !isQuerying", timeout=10_000)
        except Exception:
            try:
                self.page.reload()
                wait_for_websocket_connected(self.page)
                self.page.wait_for_timeout(1000)
            except Exception:
                pass
        # Reconnect MySQL to ensure fresh connection
        self._ensure_mysql(self.page)

    def test_quick_mode_queries(self, quality):
        self._ensure_mysql(self.page)
        for question, checks_kwargs in self.QUESTIONS_QUICK:
            self._safe_query(question, quality, "mysql", mode="quick", timeout=120_000, checks_kwargs=checks_kwargs)

    def test_simple_mode_queries_batch1(self, quality):
        self._ensure_mysql(self.page)
        for question, checks_kwargs in self.QUESTIONS_SIMPLE[:5]:
            self._safe_query(question, quality, "mysql", timeout=240_000, checks_kwargs=checks_kwargs)

    def test_simple_mode_queries_batch2(self, quality):
        self._ensure_mysql(self.page)
        for question, checks_kwargs in self.QUESTIONS_SIMPLE[5:10]:
            self._safe_query(question, quality, "mysql", timeout=240_000, checks_kwargs=checks_kwargs)

    def test_simple_mode_queries_batch3(self, quality):
        self._ensure_mysql(self.page)
        for question, checks_kwargs in self.QUESTIONS_SIMPLE[10:]:
            self._safe_query(question, quality, "mysql", timeout=240_000, checks_kwargs=checks_kwargs)

    def test_chart_queries(self, quality):
        self._ensure_mysql(self.page)
        for question, checks_kwargs in self.QUESTIONS_CHARTS:
            result = self._safe_query(question, quality, "mysql", timeout=240_000, checks_kwargs=checks_kwargs)

    def test_mysql_export_html(self, quality):
        """Export multi-turn MySQL session to HTML."""
        self._ensure_mysql(self.page)
        submit_query(self.page, "How many tables?", mode="quick", timeout=120_000)
        submit_query(self.page, "Top 5 car brands by claims", mode="simple", timeout=240_000)

        self.page.evaluate("""
            window.__exportUrl = null;
            window.__origOpen = window.open;
            window.open = function(url, target) { window.__exportUrl = url; return null; };
        """)
        self.page.locator("#export-section .btn", has_text="HTML").click()
        self.page.wait_for_function("window.__exportUrl !== null", timeout=30_000)
        export_url = self.page.evaluate("window.__exportUrl")

        new_page = self.page.context.new_page()
        base_url = self.page.evaluate("window.location.origin")
        new_page.goto(f"{base_url}{export_url}")
        new_page.wait_for_load_state("domcontentloaded")

        body = new_page.locator("body").inner_text()
        checks = {
            "html_has_content": len(body) > 100,
            "html_has_mcpdb": "MCPDB" in body,
            "html_has_turns": "table" in body.lower() or "car" in body.lower(),
        }
        quality.record("mysql", "HTML export quality", {"response": body[:200]}, checks)

        new_page.screenshot(
            path=str(self.artifact_dir / "screenshots" / "mysql_html_export_report.png"),
            full_page=True,
        )
        new_page.close()
        self.page.evaluate("window.open = window.__origOpen;")

    def test_mysql_export_pdf(self, quality):
        """Export MySQL session to PDF."""
        self._ensure_mysql(self.page)
        submit_query(self.page, "How many distinct damage types?", mode="simple", timeout=240_000)

        with self.page.expect_download(timeout=60_000) as download_info:
            self.page.locator("#export-section .btn", has_text="PDF").click()

        download = download_info.value
        dest = self.artifact_dir / "downloads" / f"mysql_{download.suggested_filename}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(dest))

        with open(dest, "rb") as f:
            header = f.read(5)
        checks = {
            "pdf_valid": header == b"%PDF-",
            "pdf_not_empty": dest.stat().st_size > 1000,
        }
        quality.record("mysql", "PDF export quality", {"response": f"PDF {dest.stat().st_size} bytes"}, checks)
        take_screenshot(self.page, "mysql_pdf_export_done", self.artifact_dir)

    def test_mysql_export_notebook(self, quality):
        """Export MySQL session to Jupyter notebook with ERD."""
        self._ensure_mysql(self.page)
        submit_query(self.page, "Show top 3 tables by row count", mode="simple", timeout=240_000)

        with self.page.expect_download() as download_info:
            self.page.locator("#export-section .btn", has_text="Notebook").click()

        download = download_info.value
        dest = self.artifact_dir / "downloads" / f"mysql_{download.suggested_filename}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(dest))

        nb = json.loads(dest.read_text())

        def _src(cell):
            return "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]

        all_src = " ".join(_src(c) for c in nb["cells"])
        code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]

        # Check ERD cell
        erd_cells = [c for c in code_cells if "b64decode" in _src(c) and "mermaid" in _src(c)]
        has_erd = len(erd_cells) > 0
        erd_valid = False
        if has_erd:
            match = re.search(r'b64decode\("([^"]+)"\)', _src(erd_cells[0]))
            if match:
                decoded = base64.b64decode(match.group(1)).decode()
                erd_valid = "erDiagram" in decoded

        checks = {
            "nb_has_cells": len(nb["cells"]) >= 4,
            "nb_has_pymysql": "pymysql" in all_src,
            "nb_conn_populated": 'CONNECTION_STRING = ""' not in all_src,
            "nb_has_db_query": "db_query" in all_src,
            "nb_has_erd": has_erd,
            "nb_erd_valid": erd_valid if has_erd else True,
            "nb_compilable_erd": True,
        }
        if has_erd:
            try:
                compile(_src(erd_cells[0]), "<test>", "exec")
            except SyntaxError:
                checks["nb_compilable_erd"] = False

        quality.record("mysql", "Notebook export quality", {"response": f"{len(nb['cells'])} cells"}, checks)
        take_screenshot(self.page, "mysql_notebook_export_done", self.artifact_dir)


# =====================================================================
#  PostgreSQL queries (portfolio_analysis)
# =====================================================================

class TestPostgreSQLQueries:
    """Run queries against remote PostgreSQL portfolio_analysis database."""

    QUESTIONS = [
        ("quick", "How many tables are in the database?", {"has_number": True}),
        ("quick", "What tables are available?", {"min_length": 30}),
        ("quick", "Describe the schema of the main tables", {"min_length": 50}),
        ("simple", "How many rows are in each table?", {"has_number": True}),
        ("simple", "What are the most common portfolio types?", {"min_length": 30}),
        ("simple", "Show a summary of the data: key statistics and ranges", {"has_number": True, "min_length": 50}),
        ("simple", "What are the column names and types across all tables?", {"min_length": 50}),
        ("simple", "Are there any NULL values in the key columns? Show the counts.", {"has_number": True}),
    ]

    PG_TIMEOUT = 300_000  # remote DB can be slow

    def _ensure_pg(self, page: Page):
        remove_all_sources(page)
        page.wait_for_timeout(300)
        connect_database(page, PG_URL, timeout=60_000)

    def _recover(self):
        """Recover UI state after timeout."""
        try:
            self.page.locator("text=New conversation").click()
            self.page.wait_for_timeout(500)
            self.page.wait_for_function("() => typeof isQuerying !== 'undefined' && !isQuerying", timeout=10_000)
        except Exception:
            try:
                self.page.reload()
                wait_for_websocket_connected(self.page)
                self.page.wait_for_timeout(1000)
            except Exception:
                pass

    @pytest.fixture(autouse=True)
    def _setup(self, clean_page: Page, artifact_dir):
        self.page = clean_page
        self.artifact_dir = artifact_dir

    def test_postgres_queries(self, quality):
        self._ensure_pg(self.page)
        for mode, question, checks_kwargs in self.QUESTIONS:
            timeout = 120_000 if mode == "quick" else self.PG_TIMEOUT
            try:
                result = submit_query(self.page, question, mode=mode, timeout=timeout)
            except Exception:
                quality.record("postgresql", question, {"response": "", "error": True}, {"no_timeout": False})
                self._recover()
                continue
            checks = _check_response(result, **checks_kwargs)
            quality.record("postgresql", question, result, checks)
            take_screenshot(self.page, f"pg_{question[:30].replace(' ', '_')}", self.artifact_dir)

    def test_postgres_export_notebook(self, quality):
        self._ensure_pg(self.page)
        try:
            submit_query(self.page, "List all tables with row counts", mode="simple", timeout=self.PG_TIMEOUT)
        except Exception:
            self._recover()
            submit_query(self.page, "What tables exist?", mode="quick", timeout=120_000)

        with self.page.expect_download() as download_info:
            self.page.locator("#export-section .btn", has_text="Notebook").click()

        download = download_info.value
        dest = self.artifact_dir / "downloads" / f"pg_{download.suggested_filename}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(dest))

        nb = json.loads(dest.read_text())

        def _src(cell):
            return "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]

        all_src = " ".join(_src(c) for c in nb["cells"])
        checks = {
            "nb_has_psycopg2": "psycopg2" in all_src,
            "nb_conn_populated": 'CONNECTION_STRING = ""' not in all_src,
            "nb_has_db_query": "db_query" in all_src,
        }
        quality.record("postgresql", "PG notebook export", {"response": f"{len(nb['cells'])} cells"}, checks)

    def test_postgres_export_html(self, quality):
        self._ensure_pg(self.page)
        try:
            submit_query(self.page, "Show portfolio summary", mode="simple", timeout=self.PG_TIMEOUT)
        except Exception:
            self._recover()
            submit_query(self.page, "How many tables?", mode="quick", timeout=120_000)

        self.page.evaluate("""
            window.__exportUrl = null;
            window.__origOpen = window.open;
            window.open = function(url, target) { window.__exportUrl = url; return null; };
        """)
        self.page.locator("#export-section .btn", has_text="HTML").click()
        self.page.wait_for_function("window.__exportUrl !== null", timeout=30_000)
        export_url = self.page.evaluate("window.__exportUrl")

        new_page = self.page.context.new_page()
        base_url = self.page.evaluate("window.location.origin")
        new_page.goto(f"{base_url}{export_url}")
        new_page.wait_for_load_state("domcontentloaded")
        body = new_page.locator("body").inner_text()

        checks = {
            "html_has_content": len(body) > 100,
            "html_has_mcpdb": "MCPDB" in body,
        }
        quality.record("postgresql", "PG HTML export", {"response": body[:200]}, checks)
        new_page.screenshot(
            path=str(self.artifact_dir / "screenshots" / "pg_html_report.png"),
            full_page=True,
        )
        new_page.close()
        self.page.evaluate("window.open = window.__origOpen;")


# =====================================================================
#  Excel file queries
# =====================================================================

class TestExcelQueries:
    """Test all 4 Excel files with multiple query types."""

    EXCEL_FILES = [
        (SMALL_XLSX, "книга_обліку", [
            ("quick", "What sheets and tables are in this workbook?", {"min_length": 20}),
            ("quick", "Describe the structure of this data", {"min_length": 30}),
            ("simple", "Summarize the income and expenses data", {"min_length": 30}),
            ("simple", "What are the totals?", {"has_number": True}),
        ]),
        (CALC_XLSX, "расчет_2025", [
            ("quick", "What is the structure of this workbook?", {"min_length": 20}),
            ("simple", "Show a summary of the key data in this workbook", {"min_length": 30}),
            ("simple", "What are the main numerical values?", {"has_number": True}),
        ]),
        (LATENCY_XLSX, "latency", [
            ("quick", "What columns are in this data?", {"min_length": 20}),
            ("simple", "What is the average inference latency?", {"has_number": True}),
            ("simple", "Show latency statistics grouped by model or category", {"has_number": True, "min_length": 50}),
            ("simple", "What is the fastest and slowest inference time?", {"has_number": True}),
        ]),
        (PAID_XLSX, "paid", [
            ("quick", "How many rows are in this data?", {"has_number": True}),
            ("quick", "What columns are available?", {"min_length": 20}),
            ("simple", "Show a summary of payments — totals and averages", {"has_number": True}),
            ("simple", "What is the distribution of payment amounts?", {"has_number": True, "min_length": 30}),
            ("simple", "What are the top 10 largest payments?", {"has_number": True}),
        ]),
    ]

    @pytest.fixture(autouse=True)
    def _setup(self, clean_page: Page, artifact_dir):
        self.page = clean_page
        self.artifact_dir = artifact_dir

    def _recover(self):
        """Recover UI state after timeout."""
        try:
            self.page.locator("text=New conversation").click()
            self.page.wait_for_timeout(500)
            self.page.wait_for_function("() => typeof isQuerying !== 'undefined' && !isQuerying", timeout=10_000)
        except Exception:
            try:
                self.page.reload()
                wait_for_websocket_connected(self.page)
                self.page.wait_for_timeout(1000)
            except Exception:
                pass

    def test_excel_queries(self, quality):
        for file_path, label, questions in self.EXCEL_FILES:
            if not Path(file_path).exists():
                print(f"  [SKIP] {label}: file not found")
                continue

            # Clean and upload for each file
            remove_all_sources(self.page)
            self.page.wait_for_timeout(300)
            try:
                upload_excel_file(self.page, file_path, timeout=60_000)
            except Exception as e:
                quality.record(f"excel:{label}", "Upload", {"response": str(e), "error": True}, {"upload_ok": False})
                continue
            take_screenshot(self.page, f"excel_{label}_uploaded", self.artifact_dir)

            for mode, question, checks_kwargs in questions:
                timeout = 120_000 if mode == "quick" else 240_000
                try:
                    result = submit_query(self.page, question, mode=mode, timeout=timeout)
                except Exception as e:
                    quality.record(f"excel:{label}", question, {"response": "", "error": True}, {"no_timeout": False})
                    self._recover()
                    continue
                checks = _check_response(result, **checks_kwargs)
                quality.record(f"excel:{label}", question, result, checks)
                take_screenshot(
                    self.page,
                    f"excel_{label}_{question[:25].replace(' ', '_')}",
                    self.artifact_dir,
                )

    def test_excel_export_notebook(self, quality):
        """Export notebook from the smallest Excel file."""
        if not Path(SMALL_XLSX).exists():
            pytest.skip("Excel file not found")

        remove_all_sources(self.page)
        self.page.wait_for_timeout(300)
        upload_excel_file(self.page, SMALL_XLSX, timeout=60_000)
        try:
            submit_query(self.page, "Summarize this data", mode="quick", timeout=120_000)
        except Exception:
            self._recover()
            submit_query(self.page, "What is in this workbook?", mode="quick", timeout=120_000)

        with self.page.expect_download() as download_info:
            self.page.locator("#export-section .btn", has_text="Notebook").click()

        download = download_info.value
        dest = self.artifact_dir / "downloads" / f"excel_{download.suggested_filename}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(dest))

        nb = json.loads(dest.read_text())

        def _src(cell):
            return "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]

        all_src = " ".join(_src(c) for c in nb["cells"])
        checks = {
            "nb_has_duckdb": "duckdb" in all_src,
            "nb_has_openpyxl": "openpyxl" in all_src or "st_read" in all_src,
            "nb_no_erd": "erDiagram" not in all_src and "b64decode" not in all_src,
            "nb_has_cells": len(nb["cells"]) >= 3,
        }
        quality.record("excel", "Excel notebook export", {"response": f"{len(nb['cells'])} cells"}, checks)

    def test_excel_export_html(self, quality):
        """Export HTML from Excel source."""
        if not Path(PAID_XLSX).exists():
            pytest.skip("Excel file not found")

        remove_all_sources(self.page)
        self.page.wait_for_timeout(300)
        upload_excel_file(self.page, PAID_XLSX, timeout=60_000)
        submit_query(self.page, "Show payment summary", mode="quick", timeout=120_000)

        self.page.evaluate("""
            window.__exportUrl = null;
            window.__origOpen = window.open;
            window.open = function(url, target) { window.__exportUrl = url; return null; };
        """)
        self.page.locator("#export-section .btn", has_text="HTML").click()
        self.page.wait_for_function("window.__exportUrl !== null", timeout=30_000)
        export_url = self.page.evaluate("window.__exportUrl")

        new_page = self.page.context.new_page()
        base_url = self.page.evaluate("window.location.origin")
        new_page.goto(f"{base_url}{export_url}")
        new_page.wait_for_load_state("domcontentloaded")
        body = new_page.locator("body").inner_text()

        checks = {"html_has_content": len(body) > 50, "html_has_mcpdb": "MCPDB" in body}
        quality.record("excel", "Excel HTML export", {"response": body[:200]}, checks)
        new_page.screenshot(
            path=str(self.artifact_dir / "screenshots" / "excel_html_report.png"),
            full_page=True,
        )
        new_page.close()
        self.page.evaluate("window.open = window.__origOpen;")


# =====================================================================
#  CSV file queries
# =====================================================================

class TestCSVQueries:
    """Test CSV files — small temp + large real files."""

    @pytest.fixture(autouse=True)
    def _setup(self, clean_page: Page, artifact_dir):
        self.page = clean_page
        self.artifact_dir = artifact_dir

    def _recover(self):
        """Recover UI state after timeout."""
        try:
            self.page.locator("text=New conversation").click()
            self.page.wait_for_timeout(500)
            self.page.wait_for_function("() => typeof isQuerying !== 'undefined' && !isQuerying", timeout=10_000)
        except Exception:
            try:
                self.page.reload()
                wait_for_websocket_connected(self.page)
                self.page.wait_for_timeout(1000)
            except Exception:
                pass

    def test_small_csv_queries(self, quality, tmp_path):
        """Create temp CSVs and run multiple queries."""
        # Create realistic test data
        csv_path = str(tmp_path / "sales.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "product", "category", "quantity", "price", "revenue"])
            import random
            random.seed(42)
            products = [("Widget", "Hardware"), ("Gadget", "Electronics"),
                        ("Doohickey", "Hardware"), ("Thingamajig", "Electronics"),
                        ("Whatchamacallit", "Other")]
            for i in range(200):
                product, category = random.choice(products)
                qty = random.randint(1, 50)
                price = round(random.uniform(5, 500), 2)
                writer.writerow([
                    f"2025-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
                    product, category, qty, price, round(qty * price, 2),
                ])

        upload_csv_files(self.page, [csv_path])
        take_screenshot(self.page, "csv_sales_uploaded", self.artifact_dir)

        questions = [
            ("quick", "How many rows are in the data?", {"has_number": True}),
            ("quick", "What columns are available?", {"min_length": 20}),
            ("simple", "What is the total revenue?", {"has_number": True}),
            ("simple", "Show revenue by product", {"has_number": True, "min_length": 30}),
            ("simple", "What is the best-selling product by quantity?", {"has_number": True}),
            ("simple", "Show monthly revenue trend", {"has_number": True}),
            ("simple", "What is the average price per category?", {"has_number": True}),
            ("simple", "Create a bar chart of revenue by product", {"min_length": 30}),
        ]

        for mode, question, checks_kwargs in questions:
            timeout = 120_000 if mode == "quick" else 240_000
            try:
                result = submit_query(self.page, question, mode=mode, timeout=timeout)
            except Exception:
                quality.record("csv:sales", question, {"response": "", "error": True}, {"no_timeout": False})
                self._recover()
                continue
            checks = _check_response(result, **checks_kwargs)
            quality.record("csv:sales", question, result, checks)
            take_screenshot(
                self.page,
                f"csv_sales_{question[:25].replace(' ', '_')}",
                self.artifact_dir,
            )

    def test_csv_export_notebook(self, quality, tmp_path):
        """Export CSV notebook and verify DuckDB setup."""
        csv_path = str(tmp_path / "test.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "name", "score"])
            for i in range(10):
                writer.writerow([i, f"item_{i}", i * 10])

        upload_csv_files(self.page, [csv_path])
        submit_query(self.page, "What is the average score?", mode="quick", timeout=90_000)

        with self.page.expect_download() as download_info:
            self.page.locator("#export-section .btn", has_text="Notebook").click()

        download = download_info.value
        dest = self.artifact_dir / "downloads" / f"csv_{download.suggested_filename}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(dest))

        nb = json.loads(dest.read_text())

        def _src(cell):
            return "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]

        all_src = " ".join(_src(c) for c in nb["cells"])
        checks = {
            "nb_has_duckdb": "duckdb" in all_src,
            "nb_has_read_csv": "read_csv_auto" in all_src,
            "nb_no_sqlalchemy": "sqlalchemy" not in all_src.lower(),
            "nb_no_erd": "erDiagram" not in all_src,
            "nb_has_cells": len(nb["cells"]) >= 3,
        }
        quality.record("csv", "CSV notebook export", {"response": f"{len(nb['cells'])} cells"}, checks)

    def test_large_csv_78mb(self, quality):
        """Upload and query the 78MB Qala CSV."""
        if not Path(LARGE_CSV).exists():
            pytest.skip(f"Large CSV not found: {LARGE_CSV}")

        upload_csv_files(self.page, [LARGE_CSV], timeout=120_000)
        take_screenshot(self.page, "csv_qala_uploaded", self.artifact_dir)

        questions = [
            ("quick", "How many rows and columns are in this data?", {"has_number": True}),
            ("quick", "What are the column names?", {"min_length": 30}),
            ("simple", "Show a summary: row count, column count, basic statistics", {"has_number": True, "min_length": 50}),
            ("simple", "What are the most common values in the first categorical column?", {"min_length": 30}),
        ]

        for mode, question, checks_kwargs in questions:
            timeout = 120_000 if mode == "quick" else 300_000
            try:
                result = submit_query(self.page, question, mode=mode, timeout=timeout)
            except Exception:
                quality.record("csv:qala_78mb", question, {"response": "", "error": True}, {"no_timeout": False})
                self._recover()
                continue
            checks = _check_response(result, **checks_kwargs)
            quality.record("csv:qala_78mb", question, result, checks)
            take_screenshot(
                self.page,
                f"csv_qala_{question[:25].replace(' ', '_')}",
                self.artifact_dir,
            )

    def test_large_csv_154mb(self, quality):
        """Upload and query the 154MB CLAIMS CSV."""
        if not Path(CLAIMS_CSV).exists():
            pytest.skip(f"Large CSV not found: {CLAIMS_CSV}")

        remove_all_sources(self.page)
        self.page.wait_for_timeout(300)
        upload_csv_files(self.page, [CLAIMS_CSV], timeout=180_000)
        take_screenshot(self.page, "csv_claims_uploaded", self.artifact_dir)

        questions = [
            ("quick", "How many rows are in the CLAIMS data?", {"has_number": True}),
            ("quick", "What are all the column names?", {"min_length": 30}),
            ("simple", "Show the distribution of claim types — counts per type", {"has_number": True, "min_length": 30}),
            ("simple", "What is the total claims amount?", {"has_number": True}),
        ]

        for mode, question, checks_kwargs in questions:
            timeout = 120_000 if mode == "quick" else 300_000
            try:
                result = submit_query(self.page, question, mode=mode, timeout=timeout)
            except Exception:
                quality.record("csv:claims_154mb", question, {"response": "", "error": True}, {"no_timeout": False})
                self._recover()
                continue
            checks = _check_response(result, **checks_kwargs)
            quality.record("csv:claims_154mb", question, result, checks)
            take_screenshot(
                self.page,
                f"csv_claims_{question[:25].replace(' ', '_')}",
                self.artifact_dir,
            )


# =====================================================================
#  Extended mode tests (longer, deeper analysis)
# =====================================================================

class TestExtendedMode:
    """Extended mode queries — comprehensive analysis."""

    @pytest.fixture(autouse=True)
    def _setup(self, clean_page: Page, artifact_dir):
        self.page = clean_page
        self.artifact_dir = artifact_dir

    @pytest.mark.slow
    def test_mysql_extended_analysis(self, quality):
        connect_database(self.page, MYSQL_URL)

        questions = [
            ("Perform a comprehensive analysis of the relationship between car brands and claim costs. Include trends, outliers, and statistical summaries.", {"min_length": 200, "has_number": True}),
            ("Analyze the distribution of claim costs. Show histograms, percentiles, and identify any anomalies.", {"min_length": 150, "has_number": True}),
        ]

        for question, checks_kwargs in questions:
            result = submit_query(self.page, question, mode="extended", timeout=480_000)
            checks = _check_response(result, **checks_kwargs)
            quality.record("mysql:extended", question, result, checks)
            take_screenshot(self.page, f"mysql_ext_{question[:25].replace(' ', '_')}", self.artifact_dir)

    @pytest.mark.slow
    def test_postgres_extended(self, quality):
        connect_database(self.page, PG_URL, timeout=60_000)

        result = submit_query(
            self.page,
            "Perform a detailed analysis of the portfolio data. Show key metrics, distributions, and identify any patterns.",
            mode="extended",
            timeout=480_000,
        )
        checks = _check_response(result, min_length=200, has_number=True)
        quality.record("postgresql:extended", "Portfolio detailed analysis", result, checks)
        take_screenshot(self.page, "pg_extended_analysis", self.artifact_dir)


# =====================================================================
#  Cross-source and edge case tests
# =====================================================================

class TestEdgeCases:
    """Edge cases, error handling, Unicode, etc."""

    @pytest.fixture(autouse=True)
    def _setup(self, clean_page: Page, artifact_dir):
        self.page = clean_page
        self.artifact_dir = artifact_dir

    def test_query_with_no_source(self, quality):
        """Query without any source connected should show helpful error."""
        result = submit_query(self.page, "How many tables?", mode="quick", timeout=30_000)
        checks = {
            "shows_message": len(result.get("response", "")) > 5,
        }
        quality.record("none", "Query with no source", result, checks)
        take_screenshot(self.page, "no_source_query", self.artifact_dir)

    def test_unicode_question(self, quality):
        """Query with Unicode characters should work."""
        connect_database(self.page, MYSQL_URL)
        result = submit_query(
            self.page,
            "Скільки таблиць є в базі даних? (How many tables?)",
            mode="quick",
            timeout=90_000,
        )
        checks = _check_response(result, no_empty_response=True)
        quality.record("mysql", "Unicode question (Ukrainian)", result, checks)
        take_screenshot(self.page, "unicode_query", self.artifact_dir)

    def test_new_conversation_resets(self, quality):
        """New Conversation button should clear chat and export section."""
        connect_database(self.page, MYSQL_URL)
        submit_query(self.page, "How many tables?", mode="quick", timeout=90_000)

        # Verify export section visible
        expect(self.page.locator("#export-section")).to_be_visible()

        # Click New Conversation
        self.page.locator("text=New conversation").click()
        self.page.wait_for_timeout(500)

        # Export should be hidden
        export_hidden = not self.page.locator("#export-section").is_visible()
        checks = {"export_hidden_after_reset": export_hidden}
        quality.record("mysql", "New conversation reset", {"response": "reset"}, checks)
        take_screenshot(self.page, "new_conversation_reset", self.artifact_dir)
