"""Microsoft SQL Server dialect."""

from __future__ import annotations

from typing import Any

from mcpdb.sources.database.dialects.base import DatabaseDialect, ExplainResult


class MSSQLDialect(DatabaseDialect):
    names = ["mssql"]

    def get_connect_args(
        self, connect_timeout: int = 10, query_timeout: int = 30
    ) -> dict[str, Any]:
        return {
            "connect_args": {
                "timeout": connect_timeout,
                "login_timeout": connect_timeout,
            }
        }

    def get_system_schemas(self) -> set[str]:
        return {
            "INFORMATION_SCHEMA", "sys", "guest",
            "db_owner", "db_accessadmin", "db_securityadmin",
            "db_ddladmin", "db_backupoperator", "db_datareader",
            "db_datawriter", "db_denydatareader", "db_denydatawriter",
        }

    def get_row_count_query(self, schema: str) -> str | None:
        return (
            "SELECT t.name AS table_name, "
            "       SUM(p.rows) AS row_count "
            "FROM sys.tables t "
            "JOIN sys.partitions p ON t.object_id = p.object_id "
            "JOIN sys.schemas s ON t.schema_id = s.schema_id "
            f"WHERE s.name = '{schema}' AND p.index_id IN (0, 1) "
            "GROUP BY t.name"
        )

    def add_limit(self, query: str, n: int) -> str:
        # SQL Server uses TOP or OFFSET-FETCH
        return f"SELECT TOP {n} * FROM ({query}) _t"

    def add_random_limit(self, query: str, n: int) -> str:
        return f"SELECT TOP {n} * FROM ({query}) _t ORDER BY NEWID()"

    def add_sampling(
        self, query: str, table: str, row_count: int, sample_size: int
    ) -> str:
        pct = max(0.1, min(100.0, (sample_size / max(row_count, 1)) * 100))
        return query.replace(table, f"{table} TABLESAMPLE({pct:.1f} PERCENT)")

    def get_sql_syntax_rules(self) -> str:
        return (
            "- Use T-SQL (SQL Server) syntax\n"
            "- String concatenation: + operator or CONCAT()\n"
            "- Use square brackets for identifier quoting: [column_name]\n"
            "- Top N rows: SELECT TOP N ... (not LIMIT)\n"
            "- Date functions: GETDATE(), DATEADD(), DATEDIFF(), FORMAT()\n"
            "- Use CAST() or CONVERT() for type conversion\n"
            "- Pagination: OFFSET x ROWS FETCH NEXT y ROWS ONLY"
        )

    def quote_identifier(self, name: str) -> str:
        return f"[{name}]"

    def get_retryable_errors(self) -> list[str]:
        return [
            "connection reset",
            "connection refused",
            "timeout",
            "Communication link failure",
            "Login timeout expired",
        ]

    def get_explain_prefix(self) -> str:
        return "SET SHOWPLAN_XML ON"

    def get_backend_pid_query(self) -> str | None:
        return "SELECT @@SPID"

    def get_cancel_query(self, pid: int) -> str | None:
        return f"KILL {pid}"
