"""Mermaid ERD rendering stability — comprehensive 30-case test suite.

Verifies mermaid diagrams render without errors for:
- Database sources (MySQL, PostgreSQL)
- CSV sources (clean, special chars, Unicode, multi-file, large)
- Excel sources (xlsx, multi-sheet)
- LLM-generated mermaid in answers
- Edge cases (empty tables, single column, many columns)

Run:
    pytest tests/web_qa/test_mermaid_stability.py --visible -v -s
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.web_qa.helpers import (
    connect_database,
    remove_all_sources,
    submit_query,
    upload_csv_files,
    upload_excel_file,
    take_screenshot,
)

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------
MYSQL_CONN = "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins"
PG_CONN = "postgresql://readonly:uPxAP3mQ3N74@34.147.20.48/portfolio_analysis?sslmode=require"

CSV_SIMPEGO = [
    os.path.expanduser("~/Downloads/policies_simpego_v2.csv"),
    os.path.expanduser("~/Downloads/claims_simpego_v2.csv"),
]

EXCEL_INFERENCE = os.path.expanduser(
    "~/Downloads/Telegram Desktop/inference_latency_results.xlsx"
)
EXCEL_PAID = os.path.expanduser("~/Downloads/Telegram Desktop/Paid.xlsx")
EXCEL_RESERVED = os.path.expanduser("~/Downloads/Telegram Desktop/Reserved.xlsx")

LOG_FILE = Path(__file__).parent / "artifacts" / "mermaid_stability.log"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def _log(msg: str):
    """Append to persistent log file and print."""
    print(msg)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(msg + "\n")


# ---------------------------------------------------------------------------
# Mermaid diagnostics
# ---------------------------------------------------------------------------
def _check_mermaid(page) -> dict:
    """Return mermaid rendering diagnostics from the current page."""
    return page.evaluate("""() => {
        const syntaxErr = document.body.innerText.includes('Syntax error in text');
        const allMermaid = document.querySelectorAll('.mermaid');
        let svgOk = 0, svgErr = 0, unrendered = 0, snippets = [];
        allMermaid.forEach(el => {
            const svg = el.querySelector('svg');
            if (svg) {
                if (svg.innerHTML.includes('Syntax error')) svgErr++;
                else svgOk++;
            } else if (el.textContent.trim()) {
                unrendered++;
                snippets.push(el.textContent.trim().substring(0, 300));
            }
        });
        return {
            hasSyntaxError: syntaxErr,
            svgOk: svgOk,
            svgErr: svgErr,
            unrendered: unrendered,
            snippets: snippets,
        };
    }""")


def _assert_mermaid_ok(page, label: str, artifact_dir, must_have_svg: bool = False):
    """Assert no mermaid errors; log + screenshot. Returns diagnostics."""
    ss_dir = artifact_dir / "screenshots" / "mermaid"
    ss_dir.mkdir(parents=True, exist_ok=True)
    take_screenshot(page, f"mermaid_{label}", ss_dir)

    diag = _check_mermaid(page)
    status = "PASS" if not diag["hasSyntaxError"] and diag["svgErr"] == 0 and diag["unrendered"] == 0 else "FAIL"
    _log(f"  [{status}] {label}: svgOk={diag['svgOk']} svgErr={diag['svgErr']} "
         f"unrendered={diag['unrendered']} syntaxErr={diag['hasSyntaxError']}")
    if diag["snippets"]:
        for s in diag["snippets"]:
            _log(f"    snippet: {s[:120]}")

    assert not diag["hasSyntaxError"], f"[{label}] Mermaid 'Syntax error in text'"
    assert diag["svgErr"] == 0, f"[{label}] {diag['svgErr']} mermaid SVG(s) contain errors"
    assert diag["unrendered"] == 0, f"[{label}] {diag['unrendered']} mermaid block(s) not rendered"
    if must_have_svg:
        assert diag["svgOk"] > 0, f"[{label}] Expected at least one SVG diagram"
    return diag


def _fresh_connect(page, web_server, connect_fn, wait_ms=5000):
    """Navigate, clear sources, connect, wait for ERD."""
    page.goto(web_server)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    remove_all_sources(page)
    page.wait_for_timeout(500)
    connect_fn(page)
    page.wait_for_timeout(wait_ms)


# ---------------------------------------------------------------------------
# 1-6: MySQL database
# ---------------------------------------------------------------------------
class TestMySQL:

    def test_01_mysql_discovery(self, page, web_server, artifact_dir):
        """MySQL bgins: initial discovery ERD."""
        _fresh_connect(page, web_server, lambda p: connect_database(p, MYSQL_CONN, "bgins"))
        _assert_mermaid_ok(page, "01_mysql_discovery", artifact_dir, must_have_svg=True)

    def test_02_mysql_erd_question(self, page, web_server, artifact_dir):
        """MySQL bgins: LLM-generated ERD in answer."""
        _fresh_connect(page, web_server, lambda p: connect_database(p, MYSQL_CONN, "bgins"))
        submit_query(page, "Draw the ER diagram for this database in mermaid", timeout=120_000)
        page.wait_for_timeout(3000)
        _assert_mermaid_ok(page, "02_mysql_erd_answer", artifact_dir)

    def test_03_mysql_relationships_question(self, page, web_server, artifact_dir):
        """MySQL bgins: ask about relationships."""
        _fresh_connect(page, web_server, lambda p: connect_database(p, MYSQL_CONN, "bgins"))
        submit_query(page, "What are the foreign key relationships between tables?", timeout=120_000)
        page.wait_for_timeout(3000)
        _assert_mermaid_ok(page, "03_mysql_relationships", artifact_dir)

    def test_04_mysql_schema_question(self, page, web_server, artifact_dir):
        """MySQL bgins: ask about schema structure."""
        _fresh_connect(page, web_server, lambda p: connect_database(p, MYSQL_CONN, "bgins"))
        submit_query(page, "List all tables and their columns", timeout=120_000)
        page.wait_for_timeout(2000)
        _assert_mermaid_ok(page, "04_mysql_schema", artifact_dir)


# ---------------------------------------------------------------------------
# 5-8: PostgreSQL database
# ---------------------------------------------------------------------------
class TestPostgreSQL:

    def test_05_pg_discovery(self, page, web_server, artifact_dir):
        """PostgreSQL portfolio: initial discovery ERD."""
        _fresh_connect(page, web_server, lambda p: connect_database(p, PG_CONN, "portfolio"))
        _assert_mermaid_ok(page, "05_pg_discovery", artifact_dir, must_have_svg=True)

    def test_06_pg_erd_question(self, page, web_server, artifact_dir):
        """PostgreSQL portfolio: LLM-generated ERD."""
        _fresh_connect(page, web_server, lambda p: connect_database(p, PG_CONN, "portfolio"))
        submit_query(page, "Show the entity-relationship diagram as mermaid", timeout=120_000)
        page.wait_for_timeout(3000)
        _assert_mermaid_ok(page, "06_pg_erd_answer", artifact_dir)

    def test_07_pg_relationships(self, page, web_server, artifact_dir):
        """PostgreSQL portfolio: ask about relationships."""
        _fresh_connect(page, web_server, lambda p: connect_database(p, PG_CONN, "portfolio"))
        submit_query(page, "What relationships exist between tables?", timeout=120_000)
        page.wait_for_timeout(3000)
        _assert_mermaid_ok(page, "07_pg_relationships", artifact_dir)

    def test_08_pg_schema(self, page, web_server, artifact_dir):
        """PostgreSQL portfolio: schema listing."""
        _fresh_connect(page, web_server, lambda p: connect_database(p, PG_CONN, "portfolio"))
        submit_query(page, "Describe the database schema", timeout=120_000)
        page.wait_for_timeout(2000)
        _assert_mermaid_ok(page, "08_pg_schema", artifact_dir)


# ---------------------------------------------------------------------------
# 9-14: Simpego CSV (German column names with umlauts, dots, special chars)
# ---------------------------------------------------------------------------
class TestSimpegoCSV:

    def _skip_if_missing(self):
        for f in CSV_SIMPEGO:
            if not os.path.exists(f):
                pytest.skip(f"CSV not found: {f}")

    def test_09_simpego_discovery(self, page, web_server, artifact_dir):
        """Simpego CSV: initial discovery ERD."""
        self._skip_if_missing()
        _fresh_connect(page, web_server, lambda p: upload_csv_files(p, CSV_SIMPEGO, "simpego"))
        _assert_mermaid_ok(page, "09_simpego_discovery", artifact_dir)

    def test_10_simpego_erd_question(self, page, web_server, artifact_dir):
        """Simpego CSV: ask for ERD diagram."""
        self._skip_if_missing()
        _fresh_connect(page, web_server, lambda p: upload_csv_files(p, CSV_SIMPEGO, "simpego"))
        submit_query(page, "Draw a mermaid ER diagram showing the structure of both tables", timeout=120_000)
        page.wait_for_timeout(3000)
        _assert_mermaid_ok(page, "10_simpego_erd_answer", artifact_dir)

    def test_11_simpego_relationships(self, page, web_server, artifact_dir):
        """Simpego CSV: ask agent to detect key relationships."""
        self._skip_if_missing()
        _fresh_connect(page, web_server, lambda p: upload_csv_files(p, CSV_SIMPEGO, "simpego"))
        submit_query(
            page,
            "Are there logical key relationships between these tables? Show a mermaid ER diagram.",
            timeout=120_000,
        )
        page.wait_for_timeout(3000)
        _assert_mermaid_ok(page, "11_simpego_relationships", artifact_dir)

    def test_12_simpego_single_file(self, page, web_server, artifact_dir):
        """Simpego: single CSV file (policies only)."""
        if not os.path.exists(CSV_SIMPEGO[0]):
            pytest.skip("Missing file")
        _fresh_connect(page, web_server, lambda p: upload_csv_files(p, [CSV_SIMPEGO[0]], "policies_only"))
        _assert_mermaid_ok(page, "12_simpego_single", artifact_dir)

    def test_13_simpego_claims_only(self, page, web_server, artifact_dir):
        """Simpego: single CSV file (claims only)."""
        if not os.path.exists(CSV_SIMPEGO[1]):
            pytest.skip("Missing file")
        _fresh_connect(page, web_server, lambda p: upload_csv_files(p, [CSV_SIMPEGO[1]], "claims_only"))
        _assert_mermaid_ok(page, "13_simpego_claims_only", artifact_dir)


# ---------------------------------------------------------------------------
# 14-17: Excel sources
# ---------------------------------------------------------------------------
class TestExcel:

    def test_14_excel_inference_latency(self, page, web_server, artifact_dir):
        """Excel: inference_latency_results.xlsx."""
        if not os.path.exists(EXCEL_INFERENCE):
            pytest.skip("File not found")
        _fresh_connect(page, web_server, lambda p: upload_excel_file(p, EXCEL_INFERENCE, "inference"))
        _assert_mermaid_ok(page, "14_excel_inference", artifact_dir)

    def test_15_excel_paid(self, page, web_server, artifact_dir):
        """Excel: Paid.xlsx."""
        if not os.path.exists(EXCEL_PAID):
            pytest.skip("File not found")
        _fresh_connect(page, web_server, lambda p: upload_excel_file(p, EXCEL_PAID, "paid"))
        _assert_mermaid_ok(page, "15_excel_paid", artifact_dir)

    def test_16_excel_reserved(self, page, web_server, artifact_dir):
        """Excel: Reserved.xlsx."""
        if not os.path.exists(EXCEL_RESERVED):
            pytest.skip("File not found")
        _fresh_connect(page, web_server, lambda p: upload_excel_file(p, EXCEL_RESERVED, "reserved"))
        _assert_mermaid_ok(page, "16_excel_reserved", artifact_dir)

    def test_17_excel_erd_question(self, page, web_server, artifact_dir):
        """Excel: ask for ERD after loading inference_latency."""
        if not os.path.exists(EXCEL_INFERENCE):
            pytest.skip("File not found")
        _fresh_connect(page, web_server, lambda p: upload_excel_file(p, EXCEL_INFERENCE, "inference"))
        submit_query(page, "Show the structure of all sheets as a mermaid diagram", timeout=120_000)
        page.wait_for_timeout(3000)
        _assert_mermaid_ok(page, "17_excel_erd_answer", artifact_dir)


# ---------------------------------------------------------------------------
# 18-24: Synthetic CSV edge cases
# ---------------------------------------------------------------------------
class TestSyntheticCSV:

    def test_18_csv_spaces_parens(self, page, web_server, artifact_dir, tmp_path):
        """CSV: column names with spaces, parens, quotes."""
        csv = tmp_path / "tricky.csv"
        csv.write_text(
            '"Order Date (UTC)","Ship-To City","Total Price (USD)","Item #","% Discount"\n'
            '"2025-01-01","NYC",100,"#101",10\n'
        )
        _fresh_connect(page, web_server, lambda p: upload_csv_files(p, [str(csv)], "tricky"))
        _assert_mermaid_ok(page, "18_csv_spaces_parens", artifact_dir)

    def test_19_csv_cyrillic(self, page, web_server, artifact_dir, tmp_path):
        """CSV: Cyrillic column names."""
        csv = tmp_path / "cyrillic.csv"
        csv.write_text(
            '"Номер","Дата","Сума (грн)","Місто (область)"\n'
            '"001","2025-01-01",50000,"Київ"\n',
            encoding="utf-8",
        )
        _fresh_connect(page, web_server, lambda p: upload_csv_files(p, [str(csv)], "cyrillic"))
        _assert_mermaid_ok(page, "19_csv_cyrillic", artifact_dir)

    def test_20_csv_related_fk(self, page, web_server, artifact_dir, tmp_path):
        """Two CSVs with inferable FK relationship."""
        (tmp_path / "orders.csv").write_text(
            "order_id,customer_id,date,total\n1,101,2025-01-01,100\n2,102,2025-01-02,250\n"
        )
        (tmp_path / "customers.csv").write_text(
            "id,name,email\n101,Alice,a@x.com\n102,Bob,b@x.com\n"
        )
        _fresh_connect(
            page, web_server,
            lambda p: upload_csv_files(p, [str(tmp_path / "orders.csv"), str(tmp_path / "customers.csv")], "related"),
        )
        _assert_mermaid_ok(page, "20_csv_related_fk", artifact_dir, must_have_svg=True)

    def test_21_csv_single_column(self, page, web_server, artifact_dir, tmp_path):
        """CSV: single column file."""
        csv = tmp_path / "single.csv"
        csv.write_text("value\n1\n2\n3\n")
        _fresh_connect(page, web_server, lambda p: upload_csv_files(p, [str(csv)], "single_col"))
        _assert_mermaid_ok(page, "21_csv_single_column", artifact_dir)

    def test_22_csv_many_columns(self, page, web_server, artifact_dir, tmp_path):
        """CSV: 50 columns (hits the _more_columns_ truncation)."""
        headers = ",".join(f"col_{i}" for i in range(50))
        values = ",".join(str(i) for i in range(50))
        csv = tmp_path / "wide.csv"
        csv.write_text(f"{headers}\n{values}\n")
        _fresh_connect(page, web_server, lambda p: upload_csv_files(p, [str(csv)], "wide"))
        _assert_mermaid_ok(page, "22_csv_many_columns", artifact_dir)

    def test_23_csv_special_table_name(self, page, web_server, artifact_dir, tmp_path):
        """CSV: filename with hyphens/spaces becomes table name."""
        csv = tmp_path / "my-data file (v2).csv"
        csv.write_text("id,name\n1,test\n")
        _fresh_connect(page, web_server, lambda p: upload_csv_files(p, [str(csv)], "special_name"))
        _assert_mermaid_ok(page, "23_csv_special_table_name", artifact_dir)

    def test_24_csv_german_chars(self, page, web_server, artifact_dir, tmp_path):
        """CSV: German umlauts and special chars like the simpego files."""
        csv = tmp_path / "german.csv"
        csv.write_text(
            '"Zahlprämie (Netto)","Rückst.","Schild.Nr","Beginn-Datum","Vermittler#"\n'
            '100.50,0,"ZH-123","2025-01-01","V001"\n',
            encoding="utf-8",
        )
        _fresh_connect(page, web_server, lambda p: upload_csv_files(p, [str(csv)], "german"))
        _assert_mermaid_ok(page, "24_csv_german_chars", artifact_dir)


# ---------------------------------------------------------------------------
# 25-30: Mixed sources and LLM answer mermaid
# ---------------------------------------------------------------------------
class TestMixed:

    def test_25_mysql_then_csv(self, page, web_server, artifact_dir, tmp_path):
        """Connect MySQL, then add a CSV — both should render."""
        csv = tmp_path / "extra.csv"
        csv.write_text("id,name,value\n1,test,100\n")
        _fresh_connect(page, web_server, lambda p: connect_database(p, MYSQL_CONN, "bgins"))
        _assert_mermaid_ok(page, "25_mysql_first", artifact_dir, must_have_svg=True)
        # Now add CSV on top
        upload_csv_files(page, [str(csv)], "extra")
        page.wait_for_timeout(3000)
        _assert_mermaid_ok(page, "25_mysql_plus_csv", artifact_dir)

    def test_26_pg_then_csv(self, page, web_server, artifact_dir, tmp_path):
        """Connect PostgreSQL, then add CSV."""
        csv = tmp_path / "extra2.csv"
        csv.write_text("id,score\n1,95\n")
        _fresh_connect(page, web_server, lambda p: connect_database(p, PG_CONN, "portfolio"))
        _assert_mermaid_ok(page, "26_pg_first", artifact_dir, must_have_svg=True)
        upload_csv_files(page, [str(csv)], "scores")
        page.wait_for_timeout(3000)
        _assert_mermaid_ok(page, "26_pg_plus_csv", artifact_dir)

    def test_27_csv_erd_question_tricky(self, page, web_server, artifact_dir, tmp_path):
        """Ask for ERD on CSV with tricky column names (LLM-generated mermaid)."""
        csv = tmp_path / "sales.csv"
        csv.write_text(
            '"Sale Date","Customer (ID)","Product Name","Price ($)","Qty"\n'
            '"2025-01-01","C-001","Widget A",29.99,5\n'
        )
        _fresh_connect(page, web_server, lambda p: upload_csv_files(p, [str(csv)], "sales"))
        submit_query(page, "Show a mermaid ER diagram of this data", timeout=120_000)
        page.wait_for_timeout(3000)
        _assert_mermaid_ok(page, "27_csv_tricky_erd_answer", artifact_dir)

    def test_28_new_conversation_mysql(self, page, web_server, artifact_dir):
        """Click 'New conversation' then reconnect MySQL — ERD should render."""
        _fresh_connect(page, web_server, lambda p: connect_database(p, MYSQL_CONN, "bgins"))
        _assert_mermaid_ok(page, "28_mysql_fresh", artifact_dir, must_have_svg=True)
        # New conversation
        page.locator("text=New conversation").click()
        page.wait_for_timeout(1000)
        # Reconnect
        remove_all_sources(page)
        connect_database(page, MYSQL_CONN, "bgins_2")
        page.wait_for_timeout(5000)
        _assert_mermaid_ok(page, "28_mysql_after_new_conv", artifact_dir, must_have_svg=True)

    def test_29_rapid_source_switch(self, page, web_server, artifact_dir, tmp_path):
        """Rapidly switch between sources — mermaid should not break."""
        csv = tmp_path / "quick.csv"
        csv.write_text("a,b,c\n1,2,3\n")
        # Connect MySQL
        _fresh_connect(page, web_server, lambda p: connect_database(p, MYSQL_CONN, "bgins"))
        page.wait_for_timeout(2000)
        # Remove and connect CSV
        remove_all_sources(page)
        page.wait_for_timeout(500)
        upload_csv_files(page, [str(csv)], "quick")
        page.wait_for_timeout(3000)
        _assert_mermaid_ok(page, "29_rapid_switch_csv", artifact_dir)
        # Switch back to MySQL
        remove_all_sources(page)
        page.wait_for_timeout(500)
        connect_database(page, MYSQL_CONN, "bgins")
        page.wait_for_timeout(5000)
        _assert_mermaid_ok(page, "29_rapid_switch_mysql", artifact_dir, must_have_svg=True)

    def test_30_three_csvs_together(self, page, web_server, artifact_dir, tmp_path):
        """Three CSVs uploaded together with relationships."""
        (tmp_path / "products.csv").write_text("product_id,name,price\n1,Widget,10\n2,Gadget,20\n")
        (tmp_path / "orders.csv").write_text("order_id,product_id,customer_id,qty\n1,1,100,5\n2,2,101,3\n")
        (tmp_path / "customers.csv").write_text("id,name,city\n100,Alice,NYC\n101,Bob,LA\n")
        files = [str(tmp_path / f) for f in ["products.csv", "orders.csv", "customers.csv"]]
        _fresh_connect(page, web_server, lambda p: upload_csv_files(p, files, "shop"))
        _assert_mermaid_ok(page, "30_three_csvs", artifact_dir, must_have_svg=True)
