"""Cancellable query runner with backend PID tracking."""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pandas as pd
from sqlalchemy import text

from mcpdb.agent.cancellation import CancellationToken, CancelledException
from mcpdb.sources.database.connector import DatabaseConnector

logger = logging.getLogger("mcpdb.sources.database.query_runner")


class CancellableQueryRunner:
    """Execute SQL queries with support for in-flight cancellation.

    Uses the dialect's backend PID query and cancel query to kill
    running queries at the database level.
    """

    def __init__(self, connector: DatabaseConnector) -> None:
        self._connector = connector
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._active_pid: int | None = None
        self._pid_lock = threading.Lock()

    async def execute(
        self,
        query: str,
        max_rows: int = 100,
        cancellation: CancellationToken | None = None,
    ) -> pd.DataFrame:
        """Execute a query with optional cancellation support.

        If cancellation is triggered during execution, attempts to
        kill the query at the database level using dialect-specific
        cancel commands.
        """
        if cancellation is None:
            # Simple path — no cancellation support needed
            return self._connector.execute_query(query, max_rows=max_rows)

        cancellation.check()

        loop = asyncio.get_event_loop()

        # Run query in thread
        query_future = loop.run_in_executor(
            self._executor,
            self._run_with_pid_tracking,
            query,
            max_rows,
        )

        # Monitor cancellation
        cancel_task = loop.create_task(self._wait_for_cancel(cancellation))

        try:
            done, pending = await asyncio.wait(
                [query_future, cancel_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if cancel_task in done:
                # Cancellation requested — try to kill the query
                self._cancel_active_query()
                query_future.cancel()
                raise CancelledException("Query cancelled by user")

            # Query completed normally
            cancel_task.cancel()
            return query_future.result()

        except asyncio.CancelledError:
            raise CancelledException("Query cancelled")

    def _run_with_pid_tracking(self, query: str, max_rows: int) -> pd.DataFrame:
        """Execute query and track the backend PID."""
        dialect = self._connector.dialect
        pid_query = dialect.get_backend_pid_query() if dialect else None

        engine = self._connector._engine
        with engine.connect() as conn:
            # Get backend PID
            if pid_query:
                try:
                    result = conn.execute(text(pid_query))
                    row = result.fetchone()
                    if row:
                        with self._pid_lock:
                            self._active_pid = row[0]
                except Exception:
                    pass  # PID tracking is best-effort

            try:
                result = conn.execute(text(query))
                if result.returns_rows:
                    df = pd.DataFrame(result.fetchmany(max_rows), columns=result.keys())
                else:
                    df = pd.DataFrame()
                return df
            finally:
                with self._pid_lock:
                    self._active_pid = None

    def _cancel_active_query(self) -> None:
        """Attempt to cancel the active query at the database level."""
        with self._pid_lock:
            pid = self._active_pid

        if pid is None:
            return

        dialect = self._connector.dialect
        if dialect is None:
            return

        cancel_query = dialect.get_cancel_query(pid)
        if cancel_query is None:
            return

        try:
            engine = self._connector._engine
            with engine.connect() as conn:
                conn.execute(text(cancel_query))
                conn.commit()
            logger.info("Cancelled query with PID %s", pid)
        except Exception as e:
            logger.warning("Failed to cancel query PID %s: %s", pid, e)

    @staticmethod
    async def _wait_for_cancel(token: CancellationToken) -> None:
        """Async task that completes when cancellation is requested."""
        while not token.is_cancelled:
            await asyncio.sleep(0.1)
