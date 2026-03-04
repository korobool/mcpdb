"""Oracle dialect."""

from __future__ import annotations

from typing import Any

from mcpdb.sources.database.dialects.base import DatabaseDialect, ExplainResult


class OracleDialect(DatabaseDialect):
    names = ["oracle"]

    def get_connect_args(
        self, connect_timeout: int = 10, query_timeout: int = 30
    ) -> dict[str, Any]:
        return {
            "connect_args": {},
        }

    def get_system_schemas(self) -> set[str]:
        return {
            "SYS", "SYSTEM", "DBSNMP", "OUTLN", "APPQOSSYS",
            "CTXSYS", "MDSYS", "OLAPSYS", "ORDDATA", "ORDSYS",
            "WMSYS", "XDB", "LBACSYS", "APEX_PUBLIC_USER",
        }

    def get_row_count_query(self, schema: str) -> str | None:
        return (
            "SELECT TABLE_NAME AS table_name, NUM_ROWS AS row_count "
            "FROM ALL_TABLES "
            f"WHERE OWNER = '{schema}'"
        )

    def add_limit(self, query: str, n: int) -> str:
        return f"SELECT * FROM ({query}) WHERE ROWNUM <= {n}"

    def add_random_limit(self, query: str, n: int) -> str:
        return f"SELECT * FROM ({query} ORDER BY DBMS_RANDOM.VALUE) WHERE ROWNUM <= {n}"

    def add_sampling(
        self, query: str, table: str, row_count: int, sample_size: int
    ) -> str:
        pct = max(0.01, min(100.0, (sample_size / max(row_count, 1)) * 100))
        return query.replace(table, f"{table} SAMPLE({pct:.2f})")

    def get_sql_syntax_rules(self) -> str:
        return (
            "- Use Oracle SQL syntax\n"
            "- String concatenation: || operator\n"
            "- Use double quotes for case-sensitive identifiers\n"
            "- No LIMIT clause — use ROWNUM or FETCH FIRST N ROWS ONLY (12c+)\n"
            "- Date functions: SYSDATE, TO_DATE(), TO_CHAR(), ADD_MONTHS()\n"
            "- NVL() instead of COALESCE() (though COALESCE also works)\n"
            "- Dual table for expressions: SELECT 1 FROM DUAL"
        )

    def get_retryable_errors(self) -> list[str]:
        return [
            "connection reset",
            "connection refused",
            "timeout",
            "ORA-03113",  # end-of-file on communication channel
            "ORA-03114",  # not connected
            "ORA-12170",  # connect timeout
        ]

    def get_explain_prefix(self) -> str:
        return "EXPLAIN PLAN FOR"

    def get_backend_pid_query(self) -> str | None:
        return "SELECT SYS_CONTEXT('USERENV', 'SID') FROM DUAL"
