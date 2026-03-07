"""Tests for v2.0.x — CSV Support.

Covers DuckDB backend, CSV loader, CsvSource, load_csv_files MCP tool,
and multi-file cross-join support.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from mcpdb.sources.csv.duckdb_backend import DuckDBBackend, _sanitize_name
from mcpdb.sources.csv.loader import (
    detect_delimiter,
    detect_encoding,
    detect_header,
    load_csv,
    load_multiple_csvs,
)
from mcpdb.sources.csv.source import CsvSource
from mcpdb.sources.registry import SourceRegistry
from mcpdb.mcp.tools.session import handle_session_tool


@pytest.fixture
def simple_csv(tmp_path) -> Path:
    """Create a simple CSV file."""
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text(
        "id,product,amount,region\n"
        "1,Widget A,100.50,North\n"
        "2,Widget B,200.75,South\n"
        "3,Widget A,150.00,North\n"
        "4,Gadget X,75.25,East\n"
        "5,Widget B,300.00,West\n"
    )
    return csv_path


@pytest.fixture
def semicolon_csv(tmp_path) -> Path:
    """Create a semicolon-delimited CSV file."""
    csv_path = tmp_path / "data.csv"
    csv_path.write_text(
        "name;value;category\n"
        "Alpha;10.5;A\n"
        "Beta;20.3;B\n"
        "Gamma;30.1;A\n"
    )
    return csv_path


@pytest.fixture
def no_header_csv(tmp_path) -> Path:
    """Create a CSV without a header row."""
    csv_path = tmp_path / "noheader.csv"
    csv_path.write_text(
        "100,200,300\n"
        "400,500,600\n"
        "700,800,900\n"
    )
    return csv_path


@pytest.fixture
def products_csv(tmp_path) -> Path:
    """Create a products CSV for join testing."""
    csv_path = tmp_path / "products.csv"
    csv_path.write_text(
        "product_name,category,unit_cost\n"
        "Widget A,electronics,50.00\n"
        "Widget B,electronics,80.00\n"
        "Gadget X,accessories,30.00\n"
    )
    return csv_path


# --- DuckDB Backend tests (v2.0.0) ---


class TestDuckDBBackend:
    def test_create_backend(self):
        backend = DuckDBBackend()
        assert backend.table_count == 0
        backend.close()

    def test_register_dataframe(self):
        backend = DuckDBBackend()
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        backend.register_dataframe("test_table", df)
        assert backend.table_count == 1
        assert "test_table" in backend.get_table_names()
        backend.close()

    def test_query(self):
        backend = DuckDBBackend()
        df = pd.DataFrame({"id": [1, 2, 3], "value": [10, 20, 30]})
        backend.register_dataframe("data", df)
        result = backend.execute_query("SELECT * FROM data WHERE value > 15")
        assert len(result) == 2
        backend.close()

    def test_aggregate_query(self):
        backend = DuckDBBackend()
        df = pd.DataFrame({"cat": ["A", "A", "B"], "val": [10, 20, 30]})
        backend.register_dataframe("data", df)
        result = backend.execute_query("SELECT cat, SUM(val) as total FROM data GROUP BY cat ORDER BY cat")
        assert result.iloc[0]["total"] == 30  # A: 10+20
        assert result.iloc[1]["total"] == 30  # B: 30
        backend.close()

    def test_max_rows_truncation(self):
        backend = DuckDBBackend()
        df = pd.DataFrame({"x": range(100)})
        backend.register_dataframe("big", df)
        result = backend.execute_query("SELECT * FROM big", max_rows=10)
        assert len(result) == 10
        assert result.attrs.get("mcpdb_truncated") is True
        backend.close()

    def test_unregister_table(self):
        backend = DuckDBBackend()
        df = pd.DataFrame({"a": [1]})
        backend.register_dataframe("temp", df)
        backend.unregister_table("temp")
        assert "temp" not in backend.get_table_names()
        backend.close()

    def test_get_table_info(self):
        backend = DuckDBBackend()
        df = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
        backend.register_dataframe("info_test", df)
        info = backend.get_table_info("info_test")
        assert len(info) >= 2
        names = [c["name"] for c in info]
        assert "id" in names
        assert "name" in names
        backend.close()

    def test_get_row_count(self):
        backend = DuckDBBackend()
        df = pd.DataFrame({"x": range(50)})
        backend.register_dataframe("counted", df)
        assert backend.get_row_count("counted") == 50
        backend.close()

    def test_join_two_tables(self):
        backend = DuckDBBackend()
        df1 = pd.DataFrame({"id": [1, 2], "name": ["Alice", "Bob"]})
        df2 = pd.DataFrame({"user_id": [1, 2, 1], "amount": [100, 200, 50]})
        backend.register_dataframe("users", df1)
        backend.register_dataframe("orders", df2)
        result = backend.execute_query(
            "SELECT u.name, SUM(o.amount) as total "
            "FROM users u JOIN orders o ON u.id = o.user_id "
            "GROUP BY u.name ORDER BY u.name"
        )
        assert len(result) == 2
        assert result.iloc[0]["name"] == "Alice"
        assert result.iloc[0]["total"] == 150
        backend.close()

    def test_load_csv_directly(self, simple_csv):
        backend = DuckDBBackend()
        row_count, col_count, col_names = backend.load_csv(
            "sales", str(simple_csv), delimiter=",", has_header=True,
        )
        assert row_count == 5
        assert col_count == 4
        assert "id" in col_names
        assert "product" in col_names
        result = backend.execute_query("SELECT COUNT(*) as cnt FROM sales")
        assert result.iloc[0]["cnt"] == 5
        backend.close()

    def test_load_csv_no_header(self, no_header_csv):
        backend = DuckDBBackend()
        row_count, col_count, col_names = backend.load_csv(
            "data", str(no_header_csv), delimiter=",", has_header=False,
        )
        assert row_count == 3
        assert col_count == 3
        assert "col_0" in col_names
        backend.close()

    def test_load_csv_semicolon(self, semicolon_csv):
        backend = DuckDBBackend()
        row_count, col_count, col_names = backend.load_csv(
            "data", str(semicolon_csv), delimiter=";", has_header=True,
        )
        assert row_count == 3
        assert "name" in col_names
        backend.close()


class TestSanitizeName:
    def test_basic(self):
        assert _sanitize_name("my_table") == "my_table"

    def test_spaces(self):
        assert _sanitize_name("my table") == "my_table"

    def test_special_chars(self):
        assert _sanitize_name("data-2024.csv") == "data_2024_csv"

    def test_starts_with_digit(self):
        assert _sanitize_name("123data") == "t_123data"


# --- CSV Loader tests (v2.0.1) ---


class TestDetectEncoding:
    def test_utf8(self, simple_csv):
        enc = detect_encoding(simple_csv)
        # chardet may report ascii, utf-8, or windows-1252 for ASCII-only content
        ascii_compatible = {"ascii", "utf-8", "windows-1252", "iso-8859-1"}
        assert enc.lower() in ascii_compatible, f"Unexpected encoding: {enc}"

    def test_latin1(self, tmp_path):
        p = tmp_path / "latin1.csv"
        p.write_bytes("name,city\nAlice,Zürich\n".encode("latin-1"))
        enc = detect_encoding(p)
        assert enc  # Should detect something


class TestDetectDelimiter:
    def test_comma(self, simple_csv):
        assert detect_delimiter(simple_csv) == ","

    def test_semicolon(self, semicolon_csv):
        assert detect_delimiter(semicolon_csv) == ";"

    def test_tab(self, tmp_path):
        p = tmp_path / "tabs.csv"
        p.write_text("a\tb\tc\n1\t2\t3\n")
        assert detect_delimiter(p) == "\t"


class TestDetectHeader:
    def test_has_header(self, simple_csv):
        assert detect_header(simple_csv) is True

    def test_no_header(self, no_header_csv):
        assert detect_header(no_header_csv) is False


class TestDetectCsv:
    def test_simple_detect(self, simple_csv):
        result = load_csv(simple_csv)
        assert result.delimiter == ","
        assert result.has_header is True
        assert result.file_path == str(simple_csv)

    def test_semicolon_detect(self, semicolon_csv):
        result = load_csv(semicolon_csv)
        assert result.delimiter == ";"

    def test_no_header_detect(self, no_header_csv):
        result = load_csv(no_header_csv)
        assert result.has_header is False

    def test_custom_table_name(self, simple_csv):
        result = load_csv(simple_csv, table_name="my_sales")
        assert result.table_name == "my_sales"

    def test_table_name_from_filename(self, simple_csv):
        result = load_csv(simple_csv)
        assert "sales" in result.table_name


class TestLoadMultipleCsvs:
    def test_two_files(self, simple_csv, products_csv):
        results = load_multiple_csvs([simple_csv, products_csv])
        assert len(results) == 2
        names = {r.table_name for r in results}
        assert len(names) == 2  # All unique

    def test_duplicate_names_resolved(self, simple_csv, tmp_path):
        # Create a second file with the same name in a different directory
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        other_csv = other_dir / "sales.csv"
        other_csv.write_text("a,b\n1,2\n")

        results = load_multiple_csvs([simple_csv, other_csv])
        names = [r.table_name for r in results]
        assert len(set(names)) == 2  # Should be unique


# --- CsvSource tests (v2.0.2) ---


class TestCsvSource:
    def test_create_single_file(self, simple_csv):
        source = CsvSource(str(simple_csv))
        assert source.source_type.value == "csv"
        assert len(source.get_tables()) == 1
        source.close()

    def test_execute_query(self, simple_csv):
        source = CsvSource(str(simple_csv))
        df = source.execute_query("SELECT product, SUM(amount) as total FROM sales GROUP BY product ORDER BY total DESC")
        assert len(df) > 0
        assert "total" in df.columns
        source.close()

    def test_get_sample(self, simple_csv):
        source = CsvSource(str(simple_csv))
        df = source.get_sample("sales", limit=2)
        assert len(df) == 2
        source.close()

    def test_metadata(self, simple_csv):
        source = CsvSource(str(simple_csv))
        meta = source.get_metadata()
        assert meta.source_type.value == "csv"
        assert "sql" in meta.capabilities
        assert len(meta.tables) == 1
        source.close()

    def test_context_description(self, simple_csv):
        source = CsvSource(str(simple_csv))
        ctx = source.get_context_description()
        assert "CSV Source" in ctx
        assert "sales" in ctx
        assert "DuckDB" in ctx
        source.close()

    def test_schema_json(self, simple_csv):
        source = CsvSource(str(simple_csv))
        import json
        schema = json.loads(source.get_schema_json())
        assert "tables" in schema
        source.close()


# --- Multi-file CsvSource tests (v2.0.3) ---


class TestCsvSourceMultiFile:
    def test_multiple_files(self, simple_csv, products_csv):
        source = CsvSource([str(simple_csv), str(products_csv)])
        assert len(source.get_tables()) == 2
        source.close()

    def test_cross_file_join(self, simple_csv, products_csv):
        source = CsvSource([str(simple_csv), str(products_csv)])
        df = source.execute_query(
            "SELECT s.product, s.amount, p.unit_cost "
            "FROM sales s "
            "JOIN products p ON s.product = p.product_name "
            "ORDER BY s.amount DESC"
        )
        assert len(df) > 0
        assert "unit_cost" in df.columns
        source.close()

    def test_cross_file_aggregate(self, simple_csv, products_csv):
        source = CsvSource([str(simple_csv), str(products_csv)])
        df = source.execute_query(
            "SELECT p.category, SUM(s.amount) as revenue "
            "FROM sales s "
            "JOIN products p ON s.product = p.product_name "
            "GROUP BY p.category"
        )
        assert len(df) > 0
        source.close()

    def test_custom_table_names(self, simple_csv, products_csv):
        source = CsvSource(
            [str(simple_csv), str(products_csv)],
            table_names=["orders", "items"],
        )
        tables = source.get_tables()
        names = {t.name for t in tables}
        assert "orders" in names
        assert "items" in names
        source.close()


# --- load_csv_files MCP tool tests ---


class TestLoadCsvFilesTool:
    def test_load_single_csv(self, simple_csv):
        registry = SourceRegistry()
        result = handle_session_tool("load_csv_files", {
            "_name": "load_csv_files",
            "file_paths": [str(simple_csv)],
        }, registry)
        text = result[0].text
        assert "Loaded CSV" in text
        assert "Source ID" in text
        assert "sales" in text
        assert len(registry) == 1
        registry.close_all()

    def test_load_multiple_csvs(self, simple_csv, products_csv):
        registry = SourceRegistry()
        result = handle_session_tool("load_csv_files", {
            "_name": "load_csv_files",
            "file_paths": [str(simple_csv), str(products_csv)],
        }, registry)
        text = result[0].text
        assert "Loaded CSV" in text
        assert "2" in text  # 2 tables
        registry.close_all()

    def test_load_csv_then_query(self, simple_csv):
        from mcpdb.mcp.tools.querying import handle_query_tool
        registry = SourceRegistry()

        # Load CSV
        handle_session_tool("load_csv_files", {
            "_name": "load_csv_files",
            "file_paths": [str(simple_csv)],
        }, registry)

        # Query it
        source_id = registry.list_sources()[0].source_id
        result = handle_query_tool("execute_sql", {
            "_name": "execute_sql",
            "source_id": source_id,
            "sql": "SELECT product, COUNT(*) as cnt FROM sales GROUP BY product ORDER BY cnt DESC",
        }, registry)
        text = result[0].text
        assert "Widget" in text
        registry.close_all()

    def test_load_nonexistent_csv(self):
        registry = SourceRegistry()
        result = handle_session_tool("load_csv_files", {
            "_name": "load_csv_files",
            "file_paths": ["/nonexistent/file.csv"],
        }, registry)
        assert "Error" in result[0].text
        assert len(registry) == 0
