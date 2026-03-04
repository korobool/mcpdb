"""MySQL dialect."""

from __future__ import annotations

from typing import Any

from mcpdb.sources.database.dialects.base import DatabaseDialect, ExplainResult


class MySQLDialect(DatabaseDialect):
    names = ["mysql", "mariadb"]

    def get_connect_args(
        self, connect_timeout: int = 10, query_timeout: int = 30
    ) -> dict[str, Any]:
        return {
            "connect_args": {
                "connect_timeout": connect_timeout,
                "read_timeout": query_timeout,
                "write_timeout": query_timeout,
            }
        }

    def get_system_schemas(self) -> set[str]:
        return {"information_schema", "mysql", "performance_schema", "sys"}

    def get_row_count_query(self, schema: str) -> str | None:
        return (
            "SELECT TABLE_NAME AS table_name, TABLE_ROWS AS row_count "
            "FROM INFORMATION_SCHEMA.TABLES "
            f"WHERE TABLE_SCHEMA = '{schema}' AND TABLE_TYPE = 'BASE TABLE'"
        )

    def add_limit(self, query: str, n: int) -> str:
        return f"SELECT * FROM ({query}) _t LIMIT {n}"

    def add_random_limit(self, query: str, n: int) -> str:
        return f"SELECT * FROM ({query}) _t ORDER BY RAND() LIMIT {n}"

    def add_sampling(
        self, query: str, table: str, row_count: int, sample_size: int
    ) -> str:
        # MySQL doesn't support TABLESAMPLE; use WHERE RAND()
        pct = sample_size / max(row_count, 1)
        return query.replace(
            f"FROM {table}", f"FROM {table} WHERE RAND() < {pct:.4f}"
        )

    def get_sql_syntax_rules(self) -> str:
        return (
            "- Use MySQL SQL syntax\n"
            "- String concatenation: CONCAT() function\n"
            "- Use backticks for identifier quoting: `column_name`\n"
            "- LIKE is case-insensitive by default (depends on collation)\n"
            "- Date functions: NOW(), CURDATE(), DATE_FORMAT(), DATEDIFF()\n"
            "- Use CAST() for type conversion\n"
            "- LIMIT/OFFSET for pagination"
        )

    def quote_identifier(self, name: str) -> str:
        return f"`{name}`"

    def get_retryable_errors(self) -> list[str]:
        return [
            "connection reset",
            "connection refused",
            "timeout",
            "Lost connection",
            "Gone away",
            "Can't connect",
        ]

    def get_explain_prefix(self) -> str:
        return "EXPLAIN FORMAT=JSON"

    def parse_explain_output(self, rows: list[dict]) -> ExplainResult:
        if not rows:
            return ExplainResult(raw_plan=rows)

        try:
            query_block = rows[0].get("query_block", rows[0]) if rows else {}
            cost = query_block.get("cost_info", {}).get("query_cost")

            return ExplainResult(
                estimated_cost=float(cost) if cost else None,
                raw_plan=rows,
            )
        except (KeyError, IndexError, TypeError):
            return ExplainResult(raw_plan=rows)

    def get_backend_pid_query(self) -> str | None:
        return "SELECT CONNECTION_ID()"

    def get_cancel_query(self, pid: int) -> str | None:
        return f"KILL QUERY {pid}"
