"""Tests for v1.4.x — Discovery & Conversation Tools.

Covers profile_table, profile_column, find_relationships, suggest_joins,
MCP resources, MCP prompts, and suggest_followups.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from mcpdb.mcp.tools.profiling import get_profiling_tools, handle_profiling_tool
from mcpdb.mcp.tools.relationships import (
    get_relationship_tools,
    handle_relationship_tool,
    _infer_relationships,
)
from mcpdb.mcp.tools.analysis import get_analysis_tools, handle_analysis_tool
from mcpdb.mcp.resources import register_resources
from mcpdb.mcp.prompts import register_prompts
from mcpdb.sources.base import ColumnInfo, TableInfo
from mcpdb.sources.registry import SourceRegistry
from mcpdb.sources.database.source import DatabaseSource


@pytest.fixture
def test_db(tmp_path) -> str:
    """Create a test SQLite database with customers, orders, products, order_items."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    c.execute("""
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT,
            city TEXT,
            segment TEXT
        )
    """)
    c.execute("""
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT,
            price REAL NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            order_date TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    """)
    c.execute("""
        CREATE TABLE order_items (
            id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)
    c.execute("CREATE INDEX idx_orders_customer ON orders(customer_id)")
    c.execute("CREATE INDEX idx_items_order ON order_items(order_id)")
    c.execute("CREATE INDEX idx_items_product ON order_items(product_id)")

    # Customers
    c.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?)", [
        (1, "Alice", "alice@test.com", "NYC", "premium"),
        (2, "Bob", "bob@test.com", "London", "standard"),
        (3, "Charlie", "charlie@test.com", "Tokyo", "premium"),
        (4, "Diana", "diana@test.com", "NYC", "standard"),
        (5, "Eve", None, "London", "premium"),
    ])

    # Products
    c.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", [
        (1, "Widget A", "electronics", 29.99),
        (2, "Widget B", "electronics", 49.99),
        (3, "Gadget X", "accessories", 15.00),
        (4, "Gadget Y", "accessories", 25.00),
    ])

    # Orders
    c.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", [
        (1, 1, "2024-01-15", "completed"),
        (2, 1, "2024-02-20", "completed"),
        (3, 2, "2024-01-25", "completed"),
        (4, 3, "2024-03-01", "pending"),
        (5, 4, "2024-03-10", "completed"),
        (6, 5, "2024-03-15", "shipped"),
    ])

    # Order items
    c.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", [
        (1, 1, 1, 2, 29.99),
        (2, 1, 3, 1, 15.00),
        (3, 2, 2, 1, 49.99),
        (4, 3, 1, 3, 29.99),
        (5, 4, 4, 2, 25.00),
        (6, 5, 2, 1, 49.99),
        (7, 6, 3, 5, 15.00),
    ])
    conn.commit()
    conn.close()
    return f"sqlite:///{db_path}"


@pytest.fixture
def registry_with_db(test_db) -> tuple[SourceRegistry, str]:
    registry = SourceRegistry()
    source = DatabaseSource(test_db)
    source_id = registry.add_source(source)
    yield registry, source_id
    registry.close_all()


# --- Profiling tools tests (v1.4.0) ---


class TestProfilingTools:
    def test_get_profiling_tools(self):
        tools = get_profiling_tools()
        names = [t.name for t in tools]
        assert "profile_table" in names
        assert "profile_column" in names

    def test_profile_table(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_profiling_tool("profile_table", {
            "_name": "profile_table",
            "source_id": source_id,
            "table_name": "customers",
        }, registry)
        text = result[0].text
        assert "Profile: customers" in text
        assert "5" in text  # row count
        assert "name" in text
        assert "email" in text
        assert "city" in text

    def test_profile_table_with_stats(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_profiling_tool("profile_table", {
            "_name": "profile_table",
            "source_id": source_id,
            "table_name": "orders",
        }, registry)
        text = result[0].text
        assert "Profile: orders" in text
        assert "customer_id" in text

    def test_profile_table_not_found(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_profiling_tool("profile_table", {
            "_name": "profile_table",
            "source_id": source_id,
            "table_name": "nonexistent",
        }, registry)
        assert "not found" in result[0].text

    def test_profile_table_shows_indexes(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_profiling_tool("profile_table", {
            "_name": "profile_table",
            "source_id": source_id,
            "table_name": "orders",
        }, registry)
        text = result[0].text
        assert "idx_orders_customer" in text or "Indexes" in text

    def test_profile_column(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_profiling_tool("profile_column", {
            "_name": "profile_column",
            "source_id": source_id,
            "table_name": "customers",
            "column_name": "city",
        }, registry)
        text = result[0].text
        assert "Column Profile: customers.city" in text
        assert "NYC" in text or "London" in text or "Tokyo" in text
        assert "Distinct values" in text

    def test_profile_column_with_nulls(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_profiling_tool("profile_column", {
            "_name": "profile_column",
            "source_id": source_id,
            "table_name": "customers",
            "column_name": "email",
        }, registry)
        text = result[0].text
        assert "Null count" in text
        assert "1" in text  # Eve has null email

    def test_profile_column_not_found(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_profiling_tool("profile_column", {
            "_name": "profile_column",
            "source_id": source_id,
            "table_name": "customers",
            "column_name": "nonexistent",
        }, registry)
        assert "not found" in result[0].text

    def test_profile_column_table_not_found(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_profiling_tool("profile_column", {
            "_name": "profile_column",
            "source_id": source_id,
            "table_name": "nonexistent",
            "column_name": "id",
        }, registry)
        assert "not found" in result[0].text

    def test_profile_column_top_n(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_profiling_tool("profile_column", {
            "_name": "profile_column",
            "source_id": source_id,
            "table_name": "customers",
            "column_name": "segment",
            "top_n": 2,
        }, registry)
        text = result[0].text
        assert "premium" in text or "standard" in text
        assert "Top" in text

    def test_profile_column_numeric(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_profiling_tool("profile_column", {
            "_name": "profile_column",
            "source_id": source_id,
            "table_name": "products",
            "column_name": "price",
        }, registry)
        text = result[0].text
        assert "Min" in text
        assert "Max" in text


# --- Relationship tools tests (v1.4.1) ---


class TestRelationshipTools:
    def test_get_relationship_tools(self):
        tools = get_relationship_tools()
        names = [t.name for t in tools]
        assert "find_relationships" in names
        assert "suggest_joins" in names

    def test_find_relationships(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_relationship_tool("find_relationships", {
            "_name": "find_relationships",
            "source_id": source_id,
        }, registry)
        text = result[0].text
        assert "Relationships" in text
        assert "FK" in text
        # Should find orders → customers FK
        assert "customer_id" in text

    def test_find_relationships_filtered(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_relationship_tool("find_relationships", {
            "_name": "find_relationships",
            "source_id": source_id,
            "table_name": "orders",
        }, registry)
        text = result[0].text
        assert "orders" in text
        assert "customer_id" in text

    def test_find_relationships_no_match(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_relationship_tool("find_relationships", {
            "_name": "find_relationships",
            "source_id": source_id,
            "table_name": "nonexistent",
        }, registry)
        assert "No relationships" in result[0].text

    def test_suggest_joins(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_relationship_tool("suggest_joins", {
            "_name": "suggest_joins",
            "source_id": source_id,
            "tables": ["customers", "orders"],
        }, registry)
        text = result[0].text
        assert "JOIN" in text
        assert "customer_id" in text

    def test_suggest_joins_three_tables(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_relationship_tool("suggest_joins", {
            "_name": "suggest_joins",
            "source_id": source_id,
            "tables": ["customers", "orders", "order_items"],
        }, registry)
        text = result[0].text
        assert "JOIN" in text

    def test_suggest_joins_invalid_table(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_relationship_tool("suggest_joins", {
            "_name": "suggest_joins",
            "source_id": source_id,
            "tables": ["customers", "nonexistent"],
        }, registry)
        assert "not found" in result[0].text

    def test_suggest_joins_no_path(self, registry_with_db):
        """Two tables with no FK relationship between them."""
        registry, source_id = registry_with_db
        result = handle_relationship_tool("suggest_joins", {
            "_name": "suggest_joins",
            "source_id": source_id,
            "tables": ["customers", "products"],
        }, registry)
        text = result[0].text
        assert "No join paths" in text

    def test_suggest_joins_example_sql(self, registry_with_db):
        registry, source_id = registry_with_db
        result = handle_relationship_tool("suggest_joins", {
            "_name": "suggest_joins",
            "source_id": source_id,
            "tables": ["customers", "orders"],
        }, registry)
        text = result[0].text
        assert "Example SQL" in text
        assert "SELECT *" in text


class TestInferRelationships:
    def test_infer_from_table_id_pattern(self):
        """Column named customer_id should infer FK to customers.id."""
        tables = [
            TableInfo(
                name="customers",
                columns=[ColumnInfo("id", "INTEGER"), ColumnInfo("name", "TEXT")],
                primary_keys=["id"],
            ),
            TableInfo(
                name="orders",
                columns=[
                    ColumnInfo("id", "INTEGER"),
                    ColumnInfo("customer_id", "INTEGER"),
                ],
                primary_keys=["id"],
            ),
        ]
        inferred = _infer_relationships(tables)
        assert len(inferred) >= 1
        rel = inferred[0]
        assert rel["source_table"] == "orders"
        assert rel["source_columns"] == ["customer_id"]
        assert rel["target_table"] == "customers"
        assert rel["type"] == "inferred"

    def test_infer_singular_match(self):
        """Column named order_id should match table 'orders' (plural)."""
        tables = [
            TableInfo(
                name="orders",
                columns=[ColumnInfo("id", "INTEGER")],
                primary_keys=["id"],
            ),
            TableInfo(
                name="line_items",
                columns=[
                    ColumnInfo("id", "INTEGER"),
                    ColumnInfo("order_id", "INTEGER"),
                ],
                primary_keys=["id"],
            ),
        ]
        inferred = _infer_relationships(tables)
        assert any(
            r["source_table"] == "line_items" and r["target_table"] == "orders"
            for r in inferred
        )

    def test_no_self_reference(self):
        """Should not infer relationship to self."""
        tables = [
            TableInfo(
                name="categories",
                columns=[
                    ColumnInfo("id", "INTEGER"),
                    ColumnInfo("category_id", "INTEGER"),
                ],
                primary_keys=["id"],
            ),
        ]
        inferred = _infer_relationships(tables)
        # Should not produce self-reference
        for r in inferred:
            assert r["source_table"] != r["target_table"]

    def test_no_duplicates(self):
        """Should not produce duplicate relationships."""
        tables = [
            TableInfo(
                name="users",
                columns=[ColumnInfo("id", "INTEGER")],
                primary_keys=["id"],
            ),
            TableInfo(
                name="posts",
                columns=[
                    ColumnInfo("id", "INTEGER"),
                    ColumnInfo("user_id", "INTEGER"),
                ],
                primary_keys=["id"],
            ),
        ]
        inferred = _infer_relationships(tables)
        keys = [
            (r["source_table"], tuple(r["source_columns"]),
             r["target_table"], tuple(r["target_columns"]))
            for r in inferred
        ]
        assert len(keys) == len(set(keys))


# --- MCP Resources tests (v1.4.2) ---


class TestMCPResources:
    @pytest.mark.asyncio
    async def test_list_resources_empty(self):
        from mcp.server import Server
        server = Server("test")
        registry = SourceRegistry()
        register_resources(server, registry)

        from mcp.types import ListResourcesRequest
        handler = server.request_handlers.get(ListResourcesRequest)
        assert handler is not None

    @pytest.mark.asyncio
    async def test_list_resources_with_source(self, registry_with_db):
        from mcp.server import Server
        from mcp.types import ListResourcesRequest
        server = Server("test")
        registry, source_id = registry_with_db
        register_resources(server, registry)

        handler = server.request_handlers[ListResourcesRequest]
        result = await handler(ListResourcesRequest(method="resources/list"))
        resources = result.root.resources
        # Should have session resources + per-source resources
        assert len(resources) >= 4  # 2 session + 2 per source

        uris = [str(r.uri) for r in resources]
        assert any("session://sources" in u for u in uris)
        assert any("session://execution_status" in u for u in uris)
        assert any(f"schema://{source_id}" in u for u in uris)
        assert any(f"erd://{source_id}" in u for u in uris)

    @pytest.mark.asyncio
    async def test_read_resource_session_sources(self, registry_with_db):
        from mcp.server import Server
        from mcp.types import ReadResourceRequest, ReadResourceRequestParams
        server = Server("test")
        registry, source_id = registry_with_db
        register_resources(server, registry)

        handler = server.request_handlers[ReadResourceRequest]
        result = await handler(ReadResourceRequest(
            method="resources/read",
            params=ReadResourceRequestParams(uri="session://sources"),
        ))
        content = result.root.contents[0].text
        data = json.loads(content)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["source_id"] == source_id

    @pytest.mark.asyncio
    async def test_read_resource_schema(self, registry_with_db):
        from mcp.server import Server
        from mcp.types import ReadResourceRequest, ReadResourceRequestParams
        server = Server("test")
        registry, source_id = registry_with_db
        register_resources(server, registry)

        handler = server.request_handlers[ReadResourceRequest]
        result = await handler(ReadResourceRequest(
            method="resources/read",
            params=ReadResourceRequestParams(uri=f"schema://{source_id}"),
        ))
        content = result.root.contents[0].text
        data = json.loads(content)
        assert "tables" in data
        assert len(data["tables"]) == 4

    @pytest.mark.asyncio
    async def test_read_resource_erd(self, registry_with_db):
        from mcp.server import Server
        from mcp.types import ReadResourceRequest, ReadResourceRequestParams
        server = Server("test")
        registry, source_id = registry_with_db
        register_resources(server, registry)

        handler = server.request_handlers[ReadResourceRequest]
        result = await handler(ReadResourceRequest(
            method="resources/read",
            params=ReadResourceRequestParams(uri=f"erd://{source_id}"),
        ))
        content = result.root.contents[0].text
        assert "erDiagram" in content
        assert "customers" in content

    @pytest.mark.asyncio
    async def test_read_resource_not_found(self, registry_with_db):
        from mcp.server import Server
        from mcp.types import ReadResourceRequest, ReadResourceRequestParams
        server = Server("test")
        registry, source_id = registry_with_db
        register_resources(server, registry)

        handler = server.request_handlers[ReadResourceRequest]
        result = await handler(ReadResourceRequest(
            method="resources/read",
            params=ReadResourceRequestParams(uri="schema://nonexistent"),
        ))
        content = result.root.contents[0].text
        assert "error" in content.lower() or "not found" in content.lower()

    @pytest.mark.asyncio
    async def test_list_resource_templates(self, registry_with_db):
        from mcp.server import Server
        from mcp.types import ListResourceTemplatesRequest
        server = Server("test")
        registry, source_id = registry_with_db
        register_resources(server, registry)

        handler = server.request_handlers[ListResourceTemplatesRequest]
        result = await handler(ListResourceTemplatesRequest(method="resources/templates/list"))
        templates = result.root.resourceTemplates
        assert len(templates) == 2
        uris = [t.uriTemplate for t in templates]
        assert "schema://{source_id}" in uris
        assert "erd://{source_id}" in uris


# --- MCP Prompts tests (v1.4.4) ---


class TestMCPPrompts:
    @pytest.mark.asyncio
    async def test_list_prompts(self):
        from mcp.server import Server
        from mcp.types import ListPromptsRequest
        server = Server("test")
        registry = SourceRegistry()
        register_prompts(server, registry)

        handler = server.request_handlers[ListPromptsRequest]
        result = await handler(ListPromptsRequest(method="prompts/list"))
        prompts = result.root.prompts
        names = [p.name for p in prompts]
        assert "explore_source" in names
        assert "deep_table_analysis" in names

    @pytest.mark.asyncio
    async def test_explore_source_prompt(self, registry_with_db):
        from mcp.server import Server
        from mcp.types import GetPromptRequest, GetPromptRequestParams
        server = Server("test")
        registry, source_id = registry_with_db
        register_prompts(server, registry)

        handler = server.request_handlers[GetPromptRequest]
        result = await handler(GetPromptRequest(
            method="prompts/get",
            params=GetPromptRequestParams(
                name="explore_source",
                arguments={"source_id": source_id},
            ),
        ))
        prompt_result = result.root
        assert len(prompt_result.messages) == 1
        text = prompt_result.messages[0].content.text
        assert "explore" in text.lower()
        assert source_id in text
        assert "customers" in text
        assert "profile_table" in text

    @pytest.mark.asyncio
    async def test_explore_source_not_found(self):
        from mcp.server import Server
        from mcp.types import GetPromptRequest, GetPromptRequestParams
        server = Server("test")
        registry = SourceRegistry()
        register_prompts(server, registry)

        handler = server.request_handlers[GetPromptRequest]
        result = await handler(GetPromptRequest(
            method="prompts/get",
            params=GetPromptRequestParams(
                name="explore_source",
                arguments={"source_id": "nonexistent"},
            ),
        ))
        text = result.root.messages[0].content.text
        assert "not found" in text.lower()

    @pytest.mark.asyncio
    async def test_deep_table_analysis_prompt(self, registry_with_db):
        from mcp.server import Server
        from mcp.types import GetPromptRequest, GetPromptRequestParams
        server = Server("test")
        registry, source_id = registry_with_db
        register_prompts(server, registry)

        handler = server.request_handlers[GetPromptRequest]
        result = await handler(GetPromptRequest(
            method="prompts/get",
            params=GetPromptRequestParams(
                name="deep_table_analysis",
                arguments={"source_id": source_id, "table_name": "customers"},
            ),
        ))
        prompt_result = result.root
        text = prompt_result.messages[0].content.text
        assert "customers" in text
        assert "profile_table" in text
        assert "profile_column" in text
        assert "name" in text  # column name

    @pytest.mark.asyncio
    async def test_deep_table_analysis_table_not_found(self, registry_with_db):
        from mcp.server import Server
        from mcp.types import GetPromptRequest, GetPromptRequestParams
        server = Server("test")
        registry, source_id = registry_with_db
        register_prompts(server, registry)

        handler = server.request_handlers[GetPromptRequest]
        result = await handler(GetPromptRequest(
            method="prompts/get",
            params=GetPromptRequestParams(
                name="deep_table_analysis",
                arguments={"source_id": source_id, "table_name": "nonexistent"},
            ),
        ))
        text = result.root.messages[0].content.text
        assert "not found" in text.lower()

    @pytest.mark.asyncio
    async def test_unknown_prompt(self, registry_with_db):
        from mcp.server import Server
        from mcp.types import GetPromptRequest, GetPromptRequestParams
        server = Server("test")
        registry, source_id = registry_with_db
        register_prompts(server, registry)

        handler = server.request_handlers[GetPromptRequest]
        result = await handler(GetPromptRequest(
            method="prompts/get",
            params=GetPromptRequestParams(
                name="unknown_prompt",
                arguments={},
            ),
        ))
        text = result.root.messages[0].content.text
        assert "Unknown" in text


# --- Follow-up generation tests (v1.4.3) ---


class TestSuggestFollowups:
    async def test_suggest_followups_no_llm(self, registry_with_db):
        registry, source_id = registry_with_db
        result = await handle_analysis_tool("suggest_followups", {
            "_name": "suggest_followups",
        }, registry, llm=None)
        assert "not configured" in result[0].text.lower()

    async def test_suggest_followups_no_sources(self):
        registry = SourceRegistry()
        result = await handle_analysis_tool("suggest_followups", {
            "_name": "suggest_followups",
        }, registry, llm="mock")
        assert "No data sources" in result[0].text

    async def test_suggest_followups_with_mock_llm(self, registry_with_db):
        """Test with a mock LLM that returns follow-up questions."""
        registry, source_id = registry_with_db

        class MockLLM:
            async def generate_json(self, messages, **kwargs):
                return [
                    "What is the average order value by customer segment?",
                    "How has order volume changed over time?",
                    "Which product category generates the most revenue?",
                ], None

        result = await handle_analysis_tool("suggest_followups", {
            "_name": "suggest_followups",
            "context": "I just looked at the top customers by revenue.",
        }, registry, llm=MockLLM())
        text = result[0].text
        assert "Follow-up Questions" in text
        assert "average order value" in text
        assert "1." in text
        assert "2." in text
        assert "3." in text

    async def test_suggest_followups_llm_error(self, registry_with_db):
        """Test graceful handling when LLM fails."""
        registry, source_id = registry_with_db

        class FailingLLM:
            async def generate_json(self, messages, **kwargs):
                raise RuntimeError("API error")

        result = await handle_analysis_tool("suggest_followups", {
            "_name": "suggest_followups",
        }, registry, llm=FailingLLM())
        assert "Failed" in result[0].text


# --- Integration: tool count tests ---


class TestToolRegistration:
    def test_all_tools_registered(self):
        """All tools (6 session + 4 query + 3 discovery + 2 profile +
        2 relationship + 5 excel + 2 analysis + 1 export + 5 experience + 3 control)."""
        from mcpdb.mcp.tools.session import get_session_tools
        from mcpdb.mcp.tools.querying import get_query_tools
        from mcpdb.mcp.tools.discovery import get_discovery_tools
        from mcpdb.mcp.tools.control import get_control_tools
        from mcpdb.mcp.tools.excel import get_excel_tools
        from mcpdb.mcp.tools.export import get_export_tools
        from mcpdb.mcp.tools.experience import get_experience_tools

        all_tools = (
            get_session_tools()
            + get_query_tools()
            + get_discovery_tools()
            + get_profiling_tools()
            + get_relationship_tools()
            + get_excel_tools()
            + get_analysis_tools()
            + get_export_tools()
            + get_experience_tools()
            + get_control_tools()
        )
        assert len(all_tools) == 33

    def test_tool_names_unique(self):
        from mcpdb.mcp.tools.session import get_session_tools
        from mcpdb.mcp.tools.querying import get_query_tools
        from mcpdb.mcp.tools.discovery import get_discovery_tools
        from mcpdb.mcp.tools.control import get_control_tools
        from mcpdb.mcp.tools.excel import get_excel_tools
        from mcpdb.mcp.tools.export import get_export_tools
        from mcpdb.mcp.tools.experience import get_experience_tools

        all_tools = (
            get_session_tools()
            + get_query_tools()
            + get_discovery_tools()
            + get_profiling_tools()
            + get_relationship_tools()
            + get_excel_tools()
            + get_analysis_tools()
            + get_export_tools()
            + get_experience_tools()
            + get_control_tools()
        )
        names = [t.name for t in all_tools]
        assert len(names) == len(set(names)), f"Duplicate tool names: {names}"

    def test_create_server_registers_all(self):
        from mcp.types import ListToolsRequest
        from mcpdb.mcp.server import create_server

        server, registry = create_server()
        assert ListToolsRequest in server.request_handlers

    def test_create_server_registers_resources(self):
        from mcp.types import ListResourcesRequest
        from mcpdb.mcp.server import create_server

        server, registry = create_server()
        assert ListResourcesRequest in server.request_handlers

    def test_create_server_registers_prompts(self):
        from mcp.types import ListPromptsRequest
        from mcpdb.mcp.server import create_server

        server, registry = create_server()
        assert ListPromptsRequest in server.request_handlers
