"""Tests for v0.1.0 + v0.1.4 — Dialect system and all dialect implementations."""

from __future__ import annotations

import pytest

from mcpdb.sources.database.dialects import create_dialect
from mcpdb.sources.database.dialects.base import DatabaseDialect, ExplainResult
from mcpdb.sources.database.dialects.postgresql import PostgreSQLDialect
from mcpdb.sources.database.dialects.mysql import MySQLDialect
from mcpdb.sources.database.dialects.sqlite import SQLiteDialect
from mcpdb.sources.database.dialects.mssql import MSSQLDialect
from mcpdb.sources.database.dialects.oracle import OracleDialect


class TestDialectFactory:
    def test_create_from_url(self):
        d = create_dialect("postgresql://user:pass@host:5432/db")
        assert isinstance(d, PostgreSQLDialect)

    def test_create_from_url_with_driver(self):
        d = create_dialect("postgresql+psycopg2://user:pass@host/db")
        assert isinstance(d, PostgreSQLDialect)

    def test_create_from_name(self):
        d = create_dialect("postgresql")
        assert isinstance(d, PostgreSQLDialect)

    def test_create_postgres_alias(self):
        d = create_dialect("postgres://user@host/db")
        assert isinstance(d, PostgreSQLDialect)

    def test_create_mysql(self):
        d = create_dialect("mysql://user@host/db")
        assert isinstance(d, MySQLDialect)

    def test_create_mariadb(self):
        d = create_dialect("mariadb://user@host/db")
        assert isinstance(d, MySQLDialect)

    def test_create_sqlite(self):
        d = create_dialect("sqlite:///test.db")
        assert isinstance(d, SQLiteDialect)

    def test_create_mssql(self):
        d = create_dialect("mssql://user@host/db")
        assert isinstance(d, MSSQLDialect)

    def test_create_oracle(self):
        d = create_dialect("oracle://user@host/db")
        assert isinstance(d, OracleDialect)

    def test_unknown_dialect_raises(self):
        with pytest.raises(ValueError, match="Unknown dialect"):
            create_dialect("unknown://host/db")


class TestPostgreSQLDialect:
    @pytest.fixture
    def dialect(self):
        return PostgreSQLDialect()

    def test_connect_args(self, dialect):
        args = dialect.get_connect_args(connect_timeout=5, query_timeout=15)
        ca = args["connect_args"]
        assert ca["connect_timeout"] == 5
        assert "15000" in ca["options"]  # query_timeout in ms

    def test_system_schemas(self, dialect):
        schemas = dialect.get_system_schemas()
        assert "pg_catalog" in schemas
        assert "information_schema" in schemas

    def test_add_limit(self, dialect):
        q = dialect.add_limit("SELECT * FROM t", 10)
        assert "LIMIT 10" in q

    def test_explain_prefix(self, dialect):
        assert "FORMAT JSON" in dialect.get_explain_prefix()
        assert "ANALYZE false" in dialect.get_explain_prefix()

    def test_parse_explain_output(self, dialect):
        rows = [{"Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "big_table",
            "Plan Rows": 2500000,
            "Total Cost": 123456.0,
        }}]
        result = dialect.parse_explain_output(rows)
        assert result.scan_type == "seq_scan"
        assert result.estimated_rows == 2500000
        assert result.estimated_cost == 123456.0
        assert not result.uses_index
        assert len(result.warnings) == 1
        assert "big_table" in result.warnings[0]

    def test_parse_explain_with_index(self, dialect):
        rows = [{"Plan": {
            "Node Type": "Index Scan",
            "Plan Rows": 1,
            "Total Cost": 8.5,
        }}]
        result = dialect.parse_explain_output(rows)
        assert result.uses_index
        assert result.scan_type == "index_scan"

    def test_row_count_query(self, dialect):
        q = dialect.get_row_count_query("public")
        assert q is not None
        assert "pg_class" in q
        assert "public" in q

    def test_column_stats_query(self, dialect):
        q = dialect.get_column_stats_query("public", "users")
        assert q is not None
        assert "pg_stats" in q

    def test_backend_pid_query(self, dialect):
        assert dialect.get_backend_pid_query() == "SELECT pg_backend_pid()"

    def test_cancel_query(self, dialect):
        assert "pg_cancel_backend(42)" in dialect.get_cancel_query(42)

    def test_sql_syntax_rules(self, dialect):
        rules = dialect.get_sql_syntax_rules()
        assert "PostgreSQL" in rules
        assert "ILIKE" in rules

    def test_quote_identifier(self, dialect):
        assert dialect.quote_identifier("name") == '"name"'

    def test_sampling(self, dialect):
        q = dialect.add_sampling(
            "SELECT * FROM orders", "orders", 1_000_000, 50_000
        )
        assert "TABLESAMPLE" in q


class TestMySQLDialect:
    @pytest.fixture
    def dialect(self):
        return MySQLDialect()

    def test_connect_args(self, dialect):
        args = dialect.get_connect_args(connect_timeout=5, query_timeout=15)
        ca = args["connect_args"]
        assert ca["connect_timeout"] == 5
        assert ca["read_timeout"] == 15

    def test_system_schemas(self, dialect):
        schemas = dialect.get_system_schemas()
        assert "mysql" in schemas
        assert "information_schema" in schemas

    def test_add_limit(self, dialect):
        assert "LIMIT 10" in dialect.add_limit("SELECT * FROM t", 10)

    def test_explain_prefix(self, dialect):
        assert "FORMAT=JSON" in dialect.get_explain_prefix()

    def test_quote_identifier(self, dialect):
        assert dialect.quote_identifier("name") == "`name`"

    def test_random_limit(self, dialect):
        assert "RAND()" in dialect.add_random_limit("SELECT * FROM t", 5)

    def test_sampling_uses_rand(self, dialect):
        q = dialect.add_sampling("SELECT * FROM orders", "orders", 1_000_000, 50_000)
        assert "RAND()" in q

    def test_backend_pid(self, dialect):
        assert "CONNECTION_ID" in dialect.get_backend_pid_query()

    def test_cancel_query(self, dialect):
        assert "KILL QUERY 42" in dialect.get_cancel_query(42)

    def test_row_count_query(self, dialect):
        q = dialect.get_row_count_query("mydb")
        assert "INFORMATION_SCHEMA" in q


class TestSQLiteDialect:
    @pytest.fixture
    def dialect(self):
        return SQLiteDialect()

    def test_connect_args(self, dialect):
        args = dialect.get_connect_args(connect_timeout=5)
        assert args["connect_args"]["timeout"] == 5

    def test_system_schemas_empty(self, dialect):
        assert dialect.get_system_schemas() == set()

    def test_add_limit(self, dialect):
        assert "LIMIT 10" in dialect.add_limit("SELECT * FROM t", 10)

    def test_explain_prefix(self, dialect):
        assert "EXPLAIN QUERY PLAN" == dialect.get_explain_prefix()

    def test_parse_explain_seq_scan(self, dialect):
        rows = [{"detail": "SCAN TABLE customers"}]
        result = dialect.parse_explain_output(rows)
        assert result.scan_type == "seq_scan"

    def test_parse_explain_index_scan(self, dialect):
        rows = [{"detail": "SEARCH TABLE customers USING INDEX idx_name"}]
        result = dialect.parse_explain_output(rows)
        assert result.uses_index
        assert result.scan_type == "index_scan"

    def test_no_backend_pid(self, dialect):
        assert dialect.get_backend_pid_query() is None

    def test_sql_syntax_rules(self, dialect):
        assert "SQLite" in dialect.get_sql_syntax_rules()


class TestMSSQLDialect:
    @pytest.fixture
    def dialect(self):
        return MSSQLDialect()

    def test_system_schemas(self, dialect):
        schemas = dialect.get_system_schemas()
        assert "sys" in schemas
        assert "INFORMATION_SCHEMA" in schemas

    def test_add_limit_uses_top(self, dialect):
        q = dialect.add_limit("SELECT * FROM t", 10)
        assert "TOP 10" in q

    def test_quote_identifier(self, dialect):
        assert dialect.quote_identifier("name") == "[name]"

    def test_explain_prefix(self, dialect):
        assert "SHOWPLAN" in dialect.get_explain_prefix()

    def test_random_limit_uses_newid(self, dialect):
        assert "NEWID()" in dialect.add_random_limit("SELECT * FROM t", 5)

    def test_sampling(self, dialect):
        q = dialect.add_sampling("SELECT * FROM orders", "orders", 1_000_000, 50_000)
        assert "TABLESAMPLE" in q
        assert "PERCENT" in q

    def test_backend_pid(self, dialect):
        assert "@@SPID" in dialect.get_backend_pid_query()

    def test_row_count_query(self, dialect):
        q = dialect.get_row_count_query("dbo")
        assert "sys.tables" in q

    def test_sql_syntax_rules(self, dialect):
        rules = dialect.get_sql_syntax_rules()
        assert "T-SQL" in rules
        assert "TOP" in rules


class TestOracleDialect:
    @pytest.fixture
    def dialect(self):
        return OracleDialect()

    def test_system_schemas(self, dialect):
        schemas = dialect.get_system_schemas()
        assert "SYS" in schemas
        assert "SYSTEM" in schemas

    def test_add_limit_uses_rownum(self, dialect):
        q = dialect.add_limit("SELECT * FROM t", 10)
        assert "ROWNUM" in q

    def test_explain_prefix(self, dialect):
        assert "EXPLAIN PLAN FOR" == dialect.get_explain_prefix()

    def test_random_limit(self, dialect):
        assert "DBMS_RANDOM" in dialect.add_random_limit("SELECT * FROM t", 5)

    def test_sampling(self, dialect):
        q = dialect.add_sampling("SELECT * FROM orders", "orders", 1_000_000, 50_000)
        assert "SAMPLE(" in q

    def test_row_count_query(self, dialect):
        q = dialect.get_row_count_query("HR")
        assert "ALL_TABLES" in q

    def test_backend_pid(self, dialect):
        assert "SYS_CONTEXT" in dialect.get_backend_pid_query()

    def test_sql_syntax_rules(self, dialect):
        rules = dialect.get_sql_syntax_rules()
        assert "Oracle" in rules
        assert "DUAL" in rules


class TestExplainResult:
    def test_defaults(self):
        r = ExplainResult()
        assert r.estimated_rows is None
        assert r.scan_type == "unknown"
        assert r.join_types == []
        assert r.uses_index is False
        assert r.warnings == []
