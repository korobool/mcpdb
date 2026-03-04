"""SQLite dialect."""

from __future__ import annotations

from typing import Any

from mcpdb.sources.database.dialects.base import DatabaseDialect, ExplainResult


class SQLiteDialect(DatabaseDialect):
    names = ["sqlite"]

    def get_connect_args(
        self, connect_timeout: int = 10, query_timeout: int = 30
    ) -> dict[str, Any]:
        return {
            "connect_args": {"timeout": connect_timeout},
        }

    def get_system_schemas(self) -> set[str]:
        return set()  # SQLite has no schemas

    def add_limit(self, query: str, n: int) -> str:
        return f"SELECT * FROM ({query}) _t LIMIT {n}"

    def get_sql_syntax_rules(self) -> str:
        return (
            "- Use SQLite SQL syntax\n"
            "- String concatenation: || operator\n"
            "- No ILIKE — use LIKE (case-insensitive by default for ASCII)\n"
            "- Date functions: DATE(), TIME(), DATETIME(), STRFTIME()\n"
            "- No native BOOLEAN type — use 0/1\n"
            "- LIMIT/OFFSET for pagination\n"
            "- Use single quotes for strings, double quotes for identifiers"
        )

    def get_explain_prefix(self) -> str:
        return "EXPLAIN QUERY PLAN"

    def parse_explain_output(self, rows: list[dict]) -> ExplainResult:
        if not rows:
            return ExplainResult(raw_plan=rows)

        warnings = []
        uses_index = False
        scan_type = "unknown"

        for row in rows:
            detail = str(row.get("detail", row.get("Detail", "")))
            if "USING INDEX" in detail.upper():
                uses_index = True
                scan_type = "index_scan"
            elif "SCAN TABLE" in detail.upper() or "SCAN" in detail.upper():
                scan_type = "seq_scan"

        return ExplainResult(
            scan_type=scan_type,
            uses_index=uses_index,
            warnings=warnings,
            raw_plan=rows,
        )
