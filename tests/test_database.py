"""Tests for v0.1.1, v0.1.2, v0.1.3 — Database connector, schema explorer, DatabaseSource.

Uses SQLite for all tests (no external database required).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mcpdb.sources.database.connector import DatabaseConnector
from mcpdb.sources.database.schema_explorer import (
    SchemaExplorer,
    TableSizeTag,
    classify_table_size,
)
from mcpdb.sources.database.source import DatabaseSource, _redact_connection_string


@pytest.fixture
def test_db(tmp_path) -> str:
    """Create a test SQLite database with sample data."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    c.execute("""
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT,
            city TEXT
        )
    """)
    c.execute("""
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    """)
    c.execute("CREATE INDEX idx_orders_customer ON orders(customer_id)")

    # Insert sample data
    customers = [
        (1, "Alice", "alice@example.com", "New York"),
        (2, "Bob", "bob@example.com", "London"),
        (3, "Charlie", "charlie@example.com", "Tokyo"),
    ]
    c.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", customers)

    orders = [
        (1, 1, 99.99, "2024-01-15"),
        (2, 1, 149.50, "2024-02-20"),
        (3, 2, 75.00, "2024-03-10"),
        (4, 3, 200.00, "2024-04-05"),
        (5, 3, 50.25, "2024-05-12"),
    ]
    c.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", orders)

    conn.commit()
    conn.close()
    return f"sqlite:///{db_path}"


# --- DatabaseConnector tests (v0.1.1) ---


class TestDatabaseConnector:
    def test_connect_and_test(self, test_db):
        connector = DatabaseConnector(test_db)
        assert connector.test_connection()
        connector.close()

    def test_execute_query(self, test_db):
        connector = DatabaseConnector(test_db)
        df = connector.execute_query("SELECT * FROM customers ORDER BY id")
        assert len(df) == 3
        assert list(df.columns) == ["id", "name", "email", "city"]
        assert df.iloc[0]["name"] == "Alice"
        connector.close()

    def test_execute_query_with_limit(self, test_db):
        connector = DatabaseConnector(test_db)
        df = connector.execute_query("SELECT * FROM customers", max_rows=2)
        assert len(df) == 2
        assert df.attrs["mcpdb_truncated"] is True
        connector.close()

    def test_execute_query_no_truncation(self, test_db):
        connector = DatabaseConnector(test_db)
        df = connector.execute_query("SELECT * FROM customers", max_rows=100)
        assert len(df) == 3
        assert df.attrs["mcpdb_truncated"] is False
        connector.close()

    def test_execute_raw(self, test_db):
        connector = DatabaseConnector(test_db)
        rows = connector.execute_raw("SELECT COUNT(*) AS cnt FROM customers")
        assert rows[0]["cnt"] == 3
        connector.close()

    def test_get_schemas(self, test_db):
        connector = DatabaseConnector(test_db)
        schemas = connector.get_schemas()
        assert "main" in schemas
        connector.close()

    def test_execute_aggregate(self, test_db):
        connector = DatabaseConnector(test_db)
        df = connector.execute_query(
            "SELECT customer_id, SUM(amount) AS total "
            "FROM orders GROUP BY customer_id ORDER BY total DESC"
        )
        assert len(df) == 3
        assert df.iloc[0]["total"] == pytest.approx(250.25)  # Charlie
        connector.close()


# --- SchemaExplorer tests (v0.1.2) ---


class TestSchemaExplorer:
    def test_explore_tables(self, test_db):
        connector = DatabaseConnector(test_db)
        explorer = SchemaExplorer(connector)
        tables = explorer.explore()

        assert len(tables) == 2
        table_names = {t.name for t in tables}
        assert table_names == {"customers", "orders"}
        connector.close()

    def test_columns(self, test_db):
        connector = DatabaseConnector(test_db)
        explorer = SchemaExplorer(connector)
        tables = explorer.explore()

        customers = next(t for t in tables if t.name == "customers")
        col_names = [c.name for c in customers.columns]
        assert "id" in col_names
        assert "name" in col_names
        assert "email" in col_names
        assert "city" in col_names
        connector.close()

    def test_row_counts(self, test_db):
        connector = DatabaseConnector(test_db)
        explorer = SchemaExplorer(connector)
        tables = explorer.explore()

        customers = next(t for t in tables if t.name == "customers")
        assert customers.row_count == 3

        orders = next(t for t in tables if t.name == "orders")
        assert orders.row_count == 5
        connector.close()

    def test_indexes(self, test_db):
        connector = DatabaseConnector(test_db)
        explorer = SchemaExplorer(connector)
        tables = explorer.explore()

        orders = next(t for t in tables if t.name == "orders")
        idx_names = [idx["name"] for idx in orders.indexes]
        assert "idx_orders_customer" in idx_names
        connector.close()

    def test_foreign_keys(self, test_db):
        connector = DatabaseConnector(test_db)
        explorer = SchemaExplorer(connector)
        fks = explorer.get_foreign_keys()

        assert len(fks) >= 1
        fk = fks[0]
        assert fk["source_table"] == "orders"
        assert fk["target_table"] == "customers"
        assert "customer_id" in fk["source_columns"]
        connector.close()


class TestTableSizeTag:
    def test_small(self):
        assert classify_table_size(100) == TableSizeTag.SMALL

    def test_medium(self):
        assert classify_table_size(50_000) == TableSizeTag.MEDIUM

    def test_large(self):
        assert classify_table_size(500_000) == TableSizeTag.LARGE

    def test_very_large(self):
        assert classify_table_size(5_000_000) == TableSizeTag.VERY_LARGE

    def test_none_defaults_medium(self):
        assert classify_table_size(None) == TableSizeTag.MEDIUM


# --- DatabaseSource tests (v0.1.3) ---


class TestDatabaseSource:
    def test_init_and_metadata(self, test_db):
        source = DatabaseSource(test_db)
        meta = source.get_metadata()

        assert meta.source_type.value == "database"
        assert len(meta.tables) == 2
        assert "sql" in meta.capabilities
        source.close()

    def test_source_id_stable(self, test_db):
        s1 = DatabaseSource(test_db)
        s2 = DatabaseSource(test_db)
        assert s1.get_metadata().source_id == s2.get_metadata().source_id
        s1.close()
        s2.close()

    def test_context_description(self, test_db):
        source = DatabaseSource(test_db)
        ctx = source.get_context_description()

        assert "customers" in ctx
        assert "orders" in ctx
        assert "3 rows" in ctx or "3" in ctx
        assert "SQLiteDialect" in ctx
        source.close()

    def test_execute_query(self, test_db):
        source = DatabaseSource(test_db)
        df = source.execute_query("SELECT * FROM customers ORDER BY id")
        assert len(df) == 3
        assert df.iloc[0]["name"] == "Alice"
        source.close()

    def test_get_sample(self, test_db):
        source = DatabaseSource(test_db)
        df = source.get_sample("customers", limit=2)
        assert len(df) == 2
        source.close()

    def test_close_idempotent(self, test_db):
        source = DatabaseSource(test_db)
        source.close()
        source.close()  # Should not raise

    def test_relationships(self, test_db):
        source = DatabaseSource(test_db)
        rels = source.get_relationships()
        assert len(rels) >= 1
        assert rels[0]["source_table"] == "orders"
        source.close()

    def test_display_name_custom(self, test_db):
        source = DatabaseSource(test_db, display_name="My Test DB")
        assert source.get_metadata().display_name == "My Test DB"
        source.close()

    def test_join_query(self, test_db):
        source = DatabaseSource(test_db)
        df = source.execute_query(
            "SELECT c.name, SUM(o.amount) AS total "
            "FROM customers c "
            "JOIN orders o ON c.id = o.customer_id "
            "GROUP BY c.name ORDER BY total DESC"
        )
        assert len(df) == 3
        assert df.iloc[0]["name"] == "Charlie"
        assert df.iloc[0]["total"] == pytest.approx(250.25)
        source.close()


class TestRedactConnectionString:
    def test_with_password(self):
        assert _redact_connection_string("postgresql://user:secret@host/db") == \
            "postgresql://user:***@host/db"

    def test_without_password(self):
        assert _redact_connection_string("sqlite:///test.db") == "sqlite:///test.db"
