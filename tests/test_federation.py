"""Tests for v2.1.x — Cross-Source Federation.

Covers cross-source engine, pushdown+transfer strategy,
and cross_source_query MCP tool.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mcpdb.sources.federation import CrossSourceEngine, execute_cross_source_query
from mcpdb.sources.csv.source import CsvSource
from mcpdb.sources.database.source import DatabaseSource
from mcpdb.sources.registry import SourceRegistry
from mcpdb.mcp.tools.querying import handle_query_tool


@pytest.fixture
def customers_db(tmp_path) -> str:
    """Create a SQLite database with customers."""
    db_path = tmp_path / "customers.db"
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    c.execute("""
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            city TEXT,
            segment TEXT
        )
    """)
    c.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", [
        (1, "Alice", "NYC", "premium"),
        (2, "Bob", "London", "standard"),
        (3, "Charlie", "Tokyo", "premium"),
        (4, "Diana", "Berlin", "standard"),
    ])
    conn.commit()
    conn.close()
    return f"sqlite:///{db_path}"


@pytest.fixture
def sales_csv(tmp_path) -> Path:
    """Create a sales CSV."""
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text(
        "order_id,customer_id,product,amount\n"
        "1,1,Widget,100.00\n"
        "2,1,Gadget,50.00\n"
        "3,2,Widget,200.00\n"
        "4,3,Widget,150.00\n"
        "5,4,Gadget,75.00\n"
    )
    return csv_path


@pytest.fixture
def products_csv(tmp_path) -> Path:
    """Create a products CSV."""
    csv_path = tmp_path / "products.csv"
    csv_path.write_text(
        "product_name,category,unit_cost\n"
        "Widget,electronics,40.00\n"
        "Gadget,accessories,25.00\n"
    )
    return csv_path


@pytest.fixture
def registry_with_all(customers_db, sales_csv, products_csv):
    """Registry with a database + two CSV files."""
    registry = SourceRegistry()

    db_source = DatabaseSource(customers_db)
    db_id = registry.add_source(db_source)

    csv_source = CsvSource(
        [str(sales_csv), str(products_csv)],
        display_name="Sales + Products CSV",
    )
    csv_id = registry.add_source(csv_source)

    yield registry, db_id, csv_id
    registry.close_all()


# --- CrossSourceEngine tests ---


class TestCrossSourceEngine:
    def test_csv_to_csv_join(self, sales_csv, products_csv):
        """Two CSV sources joined in DuckDB."""
        registry = SourceRegistry()
        csv1 = CsvSource(str(sales_csv))
        csv2 = CsvSource(str(products_csv))
        id1 = registry.add_source(csv1)
        id2 = registry.add_source(csv2)

        df = execute_cross_source_query(
            "SELECT s.product, s.amount, p.unit_cost, "
            "s.amount - p.unit_cost as profit "
            "FROM sales s JOIN products p ON s.product = p.product_name "
            "ORDER BY profit DESC",
            [id1, id2],
            registry,
        )
        assert len(df) == 5
        assert "profit" in df.columns
        registry.close_all()

    def test_db_to_csv_join(self, registry_with_all):
        """Database customers joined with CSV sales."""
        registry, db_id, csv_id = registry_with_all

        df = execute_cross_source_query(
            "SELECT c.name, c.city, SUM(s.amount) as total_spent "
            "FROM customers c "
            "JOIN sales s ON c.id = s.customer_id "
            "GROUP BY c.name, c.city "
            "ORDER BY total_spent DESC",
            [db_id, csv_id],
            registry,
        )
        assert len(df) == 4
        assert df.iloc[0]["name"] == "Bob"  # 200.00
        assert float(df.iloc[0]["total_spent"]) == 200.0

    def test_three_source_join(self, registry_with_all):
        """Database + two CSV tables."""
        registry, db_id, csv_id = registry_with_all

        df = execute_cross_source_query(
            "SELECT c.name, c.segment, s.product, "
            "p.category, s.amount "
            "FROM customers c "
            "JOIN sales s ON c.id = s.customer_id "
            "JOIN products p ON s.product = p.product_name "
            "ORDER BY s.amount DESC",
            [db_id, csv_id],
            registry,
        )
        assert len(df) == 5
        assert "category" in df.columns

    def test_aggregation_across_sources(self, registry_with_all):
        """Aggregate query spanning DB + CSV."""
        registry, db_id, csv_id = registry_with_all

        df = execute_cross_source_query(
            "SELECT c.segment, COUNT(*) as order_count, "
            "SUM(s.amount) as revenue "
            "FROM customers c "
            "JOIN sales s ON c.id = s.customer_id "
            "GROUP BY c.segment "
            "ORDER BY revenue DESC",
            [db_id, csv_id],
            registry,
        )
        assert len(df) == 2
        assert set(df["segment"]) == {"premium", "standard"}

    def test_invalid_source(self):
        """Non-existent source raises."""
        registry = SourceRegistry()
        with pytest.raises(Exception):
            execute_cross_source_query(
                "SELECT 1", ["nonexistent"], registry
            )

    def test_empty_result(self, registry_with_all):
        """Query that returns no rows."""
        registry, db_id, csv_id = registry_with_all
        df = execute_cross_source_query(
            "SELECT c.name, s.amount "
            "FROM customers c "
            "JOIN sales s ON c.id = s.customer_id "
            "WHERE s.amount > 99999",
            [db_id, csv_id],
            registry,
        )
        assert len(df) == 0


# --- cross_source_query MCP tool tests ---


class TestCrossSourceQueryTool:
    def test_cross_source_tool(self, registry_with_all):
        registry, db_id, csv_id = registry_with_all
        result = handle_query_tool("cross_source_query", {
            "_name": "cross_source_query",
            "sql": (
                "SELECT c.name, SUM(s.amount) as total "
                "FROM customers c "
                "JOIN sales s ON c.id = s.customer_id "
                "GROUP BY c.name ORDER BY total DESC"
            ),
            "source_ids": [db_id, csv_id],
        }, registry)
        text = result[0].text
        assert "Alice" in text or "Bob" in text
        assert "total" in text

    def test_cross_source_tool_no_results(self, registry_with_all):
        registry, db_id, csv_id = registry_with_all
        result = handle_query_tool("cross_source_query", {
            "_name": "cross_source_query",
            "sql": "SELECT * FROM customers WHERE id = -999",
            "source_ids": [db_id, csv_id],
        }, registry)
        text = result[0].text
        assert "no results" in text.lower()

    def test_cross_source_tool_error(self):
        registry = SourceRegistry()
        result = handle_query_tool("cross_source_query", {
            "_name": "cross_source_query",
            "sql": "SELECT 1",
            "source_ids": ["bad1", "bad2"],
        }, registry)
        assert "Error" in result[0].text
