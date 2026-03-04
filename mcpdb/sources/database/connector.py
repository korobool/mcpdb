"""Database connection management — SQLAlchemy engine, pooling, retry logic."""

from __future__ import annotations

import functools
import logging
import time
from typing import Any

import pandas as pd
import sqlalchemy as sa
from sqlalchemy import text

from mcpdb.sources.database.dialects import create_dialect
from mcpdb.sources.database.dialects.base import DatabaseDialect

logger = logging.getLogger("mcpdb.database")


def retry_on_connection_error(max_retries: int = 3, delay: float = 1.0):
    """Decorator: retry on transient connection errors with backoff."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(self: DatabaseConnector, *args, **kwargs):
            retryable = self.dialect.get_retryable_errors()
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(self, *args, **kwargs)
                except Exception as e:
                    error_str = str(e).lower()
                    if any(r.lower() in error_str for r in retryable):
                        last_error = e
                        if attempt < max_retries - 1:
                            wait = delay * (2 ** attempt)
                            logger.warning(
                                "Retryable error (attempt %d/%d): %s. Retrying in %.1fs",
                                attempt + 1, max_retries, e, wait,
                            )
                            time.sleep(wait)
                            continue
                    raise
            raise last_error  # type: ignore[misc]
        return wrapper
    return decorator


class DatabaseConnector:
    """Manages a SQLAlchemy connection to a database."""

    def __init__(
        self,
        connection_string: str,
        connect_timeout: int = 10,
        query_timeout: int = 30,
        pool_size: int = 5,
    ) -> None:
        self.connection_string = connection_string
        self.dialect: DatabaseDialect = create_dialect(connection_string)
        self._connect_timeout = connect_timeout
        self._query_timeout = query_timeout

        dialect_args = self.dialect.get_connect_args(connect_timeout, query_timeout)

        engine_kwargs: dict[str, Any] = {
            "pool_size": pool_size,
            "pool_pre_ping": True,
            "pool_recycle": 3600,
        }
        # SQLite doesn't support pool_size
        if "sqlite" in connection_string:
            engine_kwargs = {}

        engine_kwargs.update(dialect_args)

        self._engine = sa.create_engine(connection_string, **engine_kwargs)
        self._inspector = sa.inspect(self._engine)

    @property
    def engine(self) -> sa.Engine:
        return self._engine

    @property
    def inspector(self) -> sa.Inspector:
        return self._inspector

    def test_connection(self) -> bool:
        """Test that the database is reachable."""
        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error("Connection test failed: %s", e)
            return False

    @retry_on_connection_error(max_retries=3, delay=0.5)
    def execute_query(
        self, query: str, max_rows: int = 100
    ) -> pd.DataFrame:
        """Execute a SQL query and return results as a DataFrame.

        The DataFrame has an 'mcpdb_truncated' attr if rows were limited.
        """
        with self._engine.connect() as conn:
            result = conn.execute(text(query))

            if result.returns_rows:
                columns = list(result.keys())
                rows = result.fetchmany(max_rows + 1)
                truncated = len(rows) > max_rows
                if truncated:
                    rows = rows[:max_rows]

                df = pd.DataFrame(rows, columns=columns)
                df.attrs["mcpdb_truncated"] = truncated
                df.attrs["mcpdb_total_rows"] = len(df)
                return df
            else:
                # DDL or DML that returns no rows
                return pd.DataFrame()

    def execute_raw(self, query: str) -> list[dict]:
        """Execute a query and return raw list of dicts (for EXPLAIN, etc.)."""
        with self._engine.connect() as conn:
            result = conn.execute(text(query))
            if result.returns_rows:
                columns = list(result.keys())
                return [dict(zip(columns, row)) for row in result.fetchall()]
            return []

    def get_schemas(self) -> list[str]:
        """Return non-system schema names."""
        system = self.dialect.get_system_schemas()
        try:
            all_schemas = self._inspector.get_schema_names()
        except Exception:
            return ["main"]  # SQLite fallback
        return [s for s in all_schemas if s not in system]

    def close(self) -> None:
        """Dispose of the engine and connection pool."""
        self._engine.dispose()
