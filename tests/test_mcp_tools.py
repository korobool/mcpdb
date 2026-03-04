"""Tests for v0.2.0-v0.2.3 — MCP server and tools.

Tests the tool handlers directly (no MCP transport needed).
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from mcpdb.mcp.server import create_server
from mcpdb.mcp.tools.session import get_session_tools, handle_session_tool
from mcpdb.mcp.tools.querying import get_query_tools, handle_query_tool
from mcpdb.mcp.tools.discovery import get_discovery_tools, handle_discovery_tool
from mcpdb.sources.registry import SourceRegistry
from mcpdb.sources.database.source import DatabaseSource


@pytest.fixture
def test_db(tmp_path) -> str:
    """Create a test SQLite database."""
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
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    """)
    c.execute("CREATE INDEX idx_orders_customer ON orders(customer_id)")
    c.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", [
        (1, "Alice", "alice@test.com", "NYC"),
        (2, "Bob", "bob@test.com", "London"),
        (3, "Charlie", "charlie@test.com", "Tokyo"),
    ])
    c.executemany("INSERT INTO orders VALUES (?, ?, ?)", [
        (1, 1, 99.99), (2, 1, 149.50), (3, 2, 75.00),
        (4, 3, 200.00), (5, 3, 50.25),
    ])
    conn.commit()
    conn.close()
    return f"sqlite:///{db_path}"


@pytest.fixture
def registry_with_db(test_db) -> tuple[SourceRegistry, str]:
    """Registry with a connected database. Returns (registry, source_id)."""
    registry = SourceRegistry()
    source = DatabaseSource(test_db)
    source_id = registry.add_source(source)
    yield registry, source_id
    registry.close_all()


# --- Server creation tests (v0.2.0) ---


class TestServerCreation:
    def test_create_server(self):
        server, registry = create_server()
        assert server is not None
        assert registry is not None
        assert len(registry) == 0

    def test_tools_registered(self):
        """Session + query + discovery tools are registered."""
        session_tools = get_session_tools()
        query_tools = get_query_tools()
        discovery_tools = get_discovery_tools()
        total = len(session_tools) + len(query_tools) + len(discovery_tools)
        assert total == 13  # 6 session + 4 query + 3 discovery

    def test_tool_names_unique(self):
        all_tools = get_session_tools() + get_query_tools() + get_discovery_tools()
        names = [t.name for t in all_tools]
        assert len(names) == len(set(names)), f"Duplicate tool names: {names}"

    @pytest.mark.asyncio
    async def test_list_tools_via_server(self):
        server, registry = create_server()
        # The server should have a ListToolsRequest handler
        from mcp.types import ListToolsRequest
        handler = server.request_handlers.get(ListToolsRequest)
        assert handler is not None


# --- Session tools tests (v0.2.1) ---


class TestSessionTools:
    def test_connect_database(self, test_db):
        registry = SourceRegistry()
        result = handle_session_tool("connect_database", {
            "_name": "connect_database",
            "connection_string": test_db,
        }, registry)
        assert len(result) == 1
        text = result[0].text
        assert "Connected:" in text
        assert "customers" in text
        assert "orders" in text
        assert len(registry) == 1
        registry.close_all()

    def test_connect_with_display_name(self, test_db):
        registry = SourceRegistry()
        result = handle_session_tool("connect_database", {
            "_name": "connect_database",
            "connection_string": test_db,
            "display_name": "My Test DB",
        }, registry)
        assert "My Test DB" in result[0].text
        registry.close_all()

    def test_list_sources_empty(self):
        registry = SourceRegistry()
        result = handle_session_tool("list_sources", {"_name": "list_sources"}, registry)
        assert "No data sources" in result[0].text

    def test_list_sources(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_session_tool("list_sources", {"_name": "list_sources"}, registry)
        text = result[0].text
        assert source_id in text
        assert "database" in text
        assert "2 tables" in text

    def test_remove_source(self, test_db):
        registry = SourceRegistry()
        source = DatabaseSource(test_db)
        source_id = registry.add_source(source)
        result = handle_session_tool("remove_source", {
            "_name": "remove_source",
            "source_id": source_id,
        }, registry)
        assert "Disconnected" in result[0].text
        assert len(registry) == 0

    def test_remove_nonexistent(self):
        registry = SourceRegistry()
        result = handle_session_tool("remove_source", {
            "_name": "remove_source",
            "source_id": "nope",
        }, registry)
        assert "not found" in result[0].text

    def test_get_source_schema(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_session_tool("get_source_schema", {
            "_name": "get_source_schema",
            "source_id": source_id,
        }, registry)
        text = result[0].text
        assert "customers" in text
        assert "orders" in text
        assert "id" in text
        assert "name" in text


# --- Query tools tests (v0.2.2) ---


class TestQueryTools:
    def test_execute_sql(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_query_tool("execute_sql", {
            "_name": "execute_sql",
            "source_id": source_id,
            "sql": "SELECT * FROM customers ORDER BY id",
        }, registry)
        text = result[0].text
        assert "Alice" in text
        assert "Bob" in text
        assert "Charlie" in text

    def test_execute_sql_with_max_rows(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_query_tool("execute_sql", {
            "_name": "execute_sql",
            "source_id": source_id,
            "sql": "SELECT * FROM customers",
            "max_rows": 2,
        }, registry)
        text = result[0].text
        assert "truncated" in text.lower()

    def test_execute_sql_aggregate(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_query_tool("execute_sql", {
            "_name": "execute_sql",
            "source_id": source_id,
            "sql": (
                "SELECT c.name, SUM(o.amount) AS total "
                "FROM customers c JOIN orders o ON c.id = o.customer_id "
                "GROUP BY c.name ORDER BY total DESC"
            ),
        }, registry)
        text = result[0].text
        assert "Charlie" in text

    def test_execute_sql_empty(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_query_tool("execute_sql", {
            "_name": "execute_sql",
            "source_id": source_id,
            "sql": "SELECT * FROM customers WHERE id = -1",
        }, registry)
        assert "no results" in result[0].text.lower()

    def test_get_table_sample(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_query_tool("get_table_sample", {
            "_name": "get_table_sample",
            "source_id": source_id,
            "table": "customers",
            "n": 2,
        }, registry)
        text = result[0].text
        # Should have 2 rows
        assert "id" in text

    def test_validate_sql_valid(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_query_tool("validate_sql", {
            "_name": "validate_sql",
            "source_id": source_id,
            "sql": "SELECT * FROM customers",
        }, registry)
        assert "Valid" in result[0].text

    def test_validate_sql_invalid(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_query_tool("validate_sql", {
            "_name": "validate_sql",
            "source_id": source_id,
            "sql": "SELECT * FROM nonexistent_table",
        }, registry)
        assert "Invalid" in result[0].text


# --- Discovery tools tests (v0.2.3) ---


class TestDiscoveryTools:
    def test_search_schema_table(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_discovery_tool("search_schema", {
            "_name": "search_schema",
            "source_id": source_id,
            "keyword": "customer",
        }, registry)
        text = result[0].text
        assert "customers" in text

    def test_search_schema_column(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_discovery_tool("search_schema", {
            "_name": "search_schema",
            "source_id": source_id,
            "keyword": "email",
        }, registry)
        text = result[0].text
        assert "email" in text
        assert "customers" in text

    def test_search_schema_no_match(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_discovery_tool("search_schema", {
            "_name": "search_schema",
            "source_id": source_id,
            "keyword": "zzzzz",
        }, registry)
        assert "No matches" in result[0].text

    def test_explain_query(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_discovery_tool("explain_query", {
            "_name": "explain_query",
            "source_id": source_id,
            "sql": "SELECT * FROM customers",
        }, registry)
        text = result[0].text
        assert "EXPLAIN" in text
        assert "scan" in text.lower()

    def test_render_erd(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_discovery_tool("render_erd", {
            "_name": "render_erd",
            "source_id": source_id,
        }, registry)
        text = result[0].text
        assert "erDiagram" in text
        assert "customers" in text
        assert "orders" in text
