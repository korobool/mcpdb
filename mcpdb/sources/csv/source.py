"""CsvSource — QueryableSource backed by DuckDB for SQL querying of CSV files."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from mcpdb.sources.base import (
    ColumnInfo,
    QueryableSource,
    SourceMetadata,
    SourceType,
    TableInfo,
)
from mcpdb.sources.csv.duckdb_backend import DuckDBBackend
from mcpdb.sources.csv.loader import CsvLoadResult, detect_csv, detect_multiple_csvs

logger = logging.getLogger("mcpdb.csv")


def _make_source_id(file_paths: list[str]) -> str:
    """Generate a stable source ID from file paths."""
    combined = "|".join(sorted(file_paths))
    h = hashlib.md5(combined.encode()).hexdigest()[:8]
    if len(file_paths) == 1:
        name = Path(file_paths[0]).stem[:20]
    else:
        name = f"{len(file_paths)}files"
    return f"csv_{name}_{h}"


class CsvSource(QueryableSource):
    """CSV source with SQL query capability via DuckDB.

    Loads one or more CSV files into an in-memory DuckDB instance.
    All files are queryable via SQL and can be joined together.
    """

    def __init__(
        self,
        file_paths: list[str] | str,
        display_name: str | None = None,
        memory_limit: str = "2GB",
        table_names: list[str] | None = None,
    ) -> None:
        if isinstance(file_paths, str):
            file_paths = [file_paths]

        self._file_paths = [str(p) for p in file_paths]
        self._source_id = _make_source_id(self._file_paths)
        self._display_name = display_name or ", ".join(
            Path(p).name for p in self._file_paths[:3]
        )
        if len(self._file_paths) > 3:
            self._display_name += f" (+{len(self._file_paths) - 3} more)"

        self._closed = False

        # Create DuckDB backend
        self._backend = DuckDBBackend(memory_limit=memory_limit)

        # Detect CSV properties (encoding, delimiter, header)
        self._load_results: list[CsvLoadResult] = []
        self._tables: list[TableInfo] = []

        if len(file_paths) == 1:
            name_override = table_names[0] if table_names else None
            result = detect_csv(file_paths[0], table_name=name_override)
            self._load_results = [result]
        else:
            self._load_results = detect_multiple_csvs(file_paths, table_names)

        # Load CSVs directly into DuckDB (no pandas intermediary)
        for result in self._load_results:
            row_count, col_count, col_names = self._backend.load_csv(
                result.table_name,
                result.file_path,
                delimiter=result.delimiter,
                has_header=result.has_header,
            )
            result.row_count = row_count
            result.column_count = col_count
            result.columns = col_names

            # Get column type info from DuckDB
            col_info = self._backend.get_table_info(result.table_name)
            columns = [
                ColumnInfo(
                    name=ci["name"],
                    dtype=ci["type"],
                    nullable=ci.get("null", "YES") == "YES",
                )
                for ci in col_info
            ]
            self._tables.append(TableInfo(
                name=result.table_name,
                columns=columns,
                row_count=row_count,
                source_file=result.file_path,
            ))

        logger.info(
            "CsvSource created: %d file(s), %d table(s)",
            len(self._file_paths),
            len(self._tables),
        )

    @property
    def source_type(self) -> SourceType:
        return SourceType.CSV

    @property
    def backend(self) -> DuckDBBackend:
        return self._backend

    def get_metadata(self) -> SourceMetadata:
        return SourceMetadata(
            source_id=self._source_id,
            source_type=SourceType.CSV,
            display_name=self._display_name,
            tables=self._tables,
            capabilities={"sql", "python"},
            raw_info={
                "file_paths": self._file_paths,
                "load_info": [
                    {
                        "table_name": r.table_name,
                        "file_path": r.file_path,
                        "encoding": r.encoding,
                        "delimiter": r.delimiter,
                        "has_header": r.has_header,
                    }
                    for r in self._load_results
                ],
            },
        )

    def get_context_description(self) -> str:
        lines = [
            f"CSV Source: {self._display_name}",
            f"Source ID: {self._source_id}",
            f"Files ({len(self._file_paths)}):",
        ]
        for result in self._load_results:
            lines.append(
                f"  - {Path(result.file_path).name} → table '{result.table_name}' "
                f"({result.row_count:,} rows, {result.column_count} columns)"
            )
            lines.append(f"    Encoding: {result.encoding}, Delimiter: {repr(result.delimiter)}")

        lines.append(f"Tables ({len(self._tables)}):")
        for table in self._tables:
            lines.append(f"  - {table.name} ({table.row_count:,} rows)")
            for col in table.columns:
                nullable = "NULL" if col.nullable else "NOT NULL"
                lines.append(f"      {col.name}: {col.dtype} {nullable}")

        lines.append("Query engine: DuckDB (in-memory)")
        lines.append("All tables can be joined via standard SQL.")
        return "\n".join(lines)

    def execute_query(self, query: str, max_rows: int = 100) -> pd.DataFrame:
        return self._backend.execute_query(query, max_rows=max_rows)

    def get_sample(self, table_name: str, limit: int = 5) -> pd.DataFrame:
        return self._backend.execute_query(
            f'SELECT * FROM "{table_name}" LIMIT {limit}',
            max_rows=limit,
        )

    def close(self) -> None:
        if not self._closed:
            self._backend.close()
            self._closed = True
            logger.info("CsvSource closed: %s", self._display_name)
