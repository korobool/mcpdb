"""PostgreSQL dialect."""

from __future__ import annotations

from typing import Any

from mcpdb.sources.database.dialects.base import DatabaseDialect, ExplainResult


class PostgreSQLDialect(DatabaseDialect):
    names = ["postgresql", "postgres"]

    def get_connect_args(
        self, connect_timeout: int = 10, query_timeout: int = 30
    ) -> dict[str, Any]:
        return {
            "connect_args": {
                "connect_timeout": connect_timeout,
                "options": f"-c statement_timeout={query_timeout * 1000}",
            }
        }

    def get_system_schemas(self) -> set[str]:
        return {"information_schema", "pg_catalog", "pg_toast"}

    def get_row_count_query(self, schema: str) -> str | None:
        return (
            "SELECT relname AS table_name, "
            "       reltuples::bigint AS row_count "
            "FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            f"WHERE n.nspname = '{schema}' AND c.relkind = 'r'"
        )

    def get_column_stats_query(self, schema: str, table: str) -> str | None:
        return (
            "SELECT attname AS column_name, "
            "       n_distinct, null_frac, avg_width "
            "FROM pg_stats "
            f"WHERE schemaname = '{schema}' AND tablename = '{table}'"
        )

    def get_index_details_query(self, schema: str, table: str) -> str | None:
        return (
            "SELECT indexname, indexdef "
            "FROM pg_indexes "
            f"WHERE schemaname = '{schema}' AND tablename = '{table}'"
        )

    def add_limit(self, query: str, n: int) -> str:
        return f"SELECT * FROM ({query}) _t LIMIT {n}"

    def add_sampling(
        self, query: str, table: str, row_count: int, sample_size: int
    ) -> str:
        pct = max(0.1, min(100.0, (sample_size / max(row_count, 1)) * 100))
        return query.replace(table, f"{table} TABLESAMPLE SYSTEM({pct:.1f})")

    def get_sql_syntax_rules(self) -> str:
        return (
            "- Use PostgreSQL SQL syntax\n"
            "- String concatenation: || operator\n"
            "- Case-sensitive identifiers must be double-quoted\n"
            "- Use ILIKE for case-insensitive LIKE\n"
            "- Date functions: NOW(), CURRENT_DATE, EXTRACT(), DATE_TRUNC()\n"
            "- Use :: for type casting (e.g., '2024-01-01'::date)\n"
            "- LIMIT/OFFSET for pagination"
        )

    def get_retryable_errors(self) -> list[str]:
        return [
            "connection reset",
            "connection refused",
            "timeout",
            "could not connect",
            "server closed the connection unexpectedly",
            "SSL connection has been closed unexpectedly",
        ]

    def get_explain_prefix(self) -> str:
        return "EXPLAIN (FORMAT JSON, ANALYZE false)"

    def parse_explain_output(self, rows: list[dict]) -> ExplainResult:
        if not rows:
            return ExplainResult(raw_plan=rows)

        try:
            # PostgreSQL EXPLAIN JSON returns a list with one dict containing "Plan"
            plan_data = rows[0] if isinstance(rows[0], dict) else rows
            if isinstance(plan_data, list) and len(plan_data) > 0:
                plan_data = plan_data[0]

            plan = plan_data.get("Plan", plan_data)

            scan_type = plan.get("Node Type", "unknown").lower().replace(" ", "_")
            estimated_rows = plan.get("Plan Rows")
            estimated_cost = plan.get("Total Cost")
            uses_index = "index" in scan_type

            # Collect join types from plan tree
            join_types = []
            warnings = []
            self._walk_plan(plan, join_types, warnings)

            return ExplainResult(
                estimated_rows=int(estimated_rows) if estimated_rows else None,
                estimated_cost=float(estimated_cost) if estimated_cost else None,
                scan_type=scan_type,
                join_types=join_types,
                uses_index=uses_index,
                warnings=warnings,
                raw_plan=rows,
            )
        except (KeyError, IndexError, TypeError):
            return ExplainResult(raw_plan=rows)

    def _walk_plan(
        self, node: dict, join_types: list[str], warnings: list[str]
    ) -> None:
        """Recursively walk EXPLAIN plan tree."""
        node_type = node.get("Node Type", "")
        if "Join" in node_type or "Loop" in node_type:
            join_types.append(node_type.lower().replace(" ", "_"))
        if node_type == "Seq Scan":
            rows = node.get("Plan Rows", 0)
            table = node.get("Relation Name", "")
            if rows and rows > 100_000:
                warnings.append(f"sequential scan on {table} ({rows:,} rows)")
        for child in node.get("Plans", []):
            self._walk_plan(child, join_types, warnings)

    def get_backend_pid_query(self) -> str | None:
        return "SELECT pg_backend_pid()"

    def get_cancel_query(self, pid: int) -> str | None:
        return f"SELECT pg_cancel_backend({pid})"
