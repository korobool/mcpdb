"""ExcelSource — dual QueryableSource + SpreadsheetSource for Excel workbooks."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from mcpdb.sources.base import (
    ColumnInfo,
    QueryableSource,
    SpreadsheetSource,
    SourceMetadata,
    SourceType,
    TableInfo,
)
from mcpdb.sources.csv.duckdb_backend import DuckDBBackend
from mcpdb.sources.excel.cell_grid import CellGrid
from mcpdb.sources.excel.formula_clusters import find_formula_clusters
from mcpdb.sources.excel.formula_deps import build_dependency_graph
from mcpdb.sources.excel.structure_analyzer import DetectedTable, analyze_sheet
from mcpdb.sources.excel.workbook_reader import WorkbookReader

logger = logging.getLogger("mcpdb.excel")


class ExcelSource(QueryableSource, SpreadsheetSource):
    """Excel workbook source with structure analysis and SQL querying.

    Detected tables are extracted as DataFrames and registered in DuckDB
    for SQL querying (QueryableSource). Spreadsheet-specific features like
    cell ranges, formulas, and text regions are also available (SpreadsheetSource).

    Context enrichment: text regions, formula clusters, and dependency analysis
    are included in the LLM context alongside table schemas.
    """

    def __init__(
        self,
        file_path: str | Path,
        display_name: str | None = None,
        memory_limit: str = "2GB",
    ) -> None:
        self._path = str(file_path)
        self._display_name = display_name or Path(file_path).name
        h = hashlib.md5(self._path.encode()).hexdigest()[:8]
        self._source_id = f"excel_{Path(file_path).stem[:20]}_{h}"
        self._closed = False

        # Read workbook
        self._reader = WorkbookReader(file_path)

        # Analyze structure
        self._sheet_analysis: dict[str, dict[str, Any]] = {}
        self._detected_tables: list[DetectedTable] = []
        self._tables: list[TableInfo] = []

        # Formula analysis (built lazily per sheet, cached)
        self._formula_cache: dict[str, list[dict[str, str]]] = {}
        self._cluster_cache: dict[str, Any] = {}
        self._dep_graph_cache: dict[str, Any] = {}

        # DuckDB for extracted tables
        self._backend = DuckDBBackend(memory_limit=memory_limit)

        for sheet_name in self._reader.sheet_names:
            grid = self._reader.read_sheet(sheet_name)
            analysis = analyze_sheet(grid, sheet_name)
            self._sheet_analysis[sheet_name] = analysis

            for table in analysis["tables"]:
                self._detected_tables.append(table)
                df = self._extract_table_df(grid, table)
                if df is not None and not df.empty:
                    tname = f"{Path(file_path).stem}_{sheet_name}_{table.range_str}".replace(":", "_")
                    tname = tname.replace(" ", "_").replace("-", "_")
                    self._backend.register_dataframe(tname, df)

                    columns = [
                        ColumnInfo(
                            name=str(col),
                            dtype=str(df[col].dtype),
                            nullable=bool(df[col].isnull().any()),
                        )
                        for col in df.columns
                    ]
                    self._tables.append(TableInfo(
                        name=tname,
                        columns=columns,
                        row_count=len(df),
                        sheet_name=sheet_name,
                    ))

        # Pre-analyze formulas for all sheets
        for sheet_name in self._reader.sheet_names:
            self._analyze_formulas(sheet_name)

        logger.info(
            "ExcelSource created: %s (%d sheets, %d tables detected)",
            self._display_name,
            len(self._reader.sheet_names),
            len(self._tables),
        )

    def _extract_table_df(self, grid: CellGrid, table: DetectedTable) -> pd.DataFrame | None:
        """Extract a detected table as a DataFrame."""
        headers = table.headers
        rows = []
        for r in range(table.data_start_row, table.data_end_row + 1):
            row_data = []
            for c in range(table.start_col, table.end_col + 1):
                row_data.append(grid.get(r, c).value)
            rows.append(row_data)

        if not rows:
            return None

        # Ensure we have the right number of columns
        expected_cols = table.end_col - table.start_col + 1
        if len(headers) < expected_cols:
            headers.extend([f"col_{i}" for i in range(len(headers), expected_cols)])

        return pd.DataFrame(rows, columns=headers[:expected_cols])

    def _analyze_formulas(self, sheet_name: str) -> None:
        """Analyze formulas for a sheet and cache results."""
        formulas = self._reader.get_formulas(sheet_name)
        self._formula_cache[sheet_name] = formulas
        if formulas:
            self._cluster_cache[sheet_name] = find_formula_clusters(formulas)
            self._dep_graph_cache[sheet_name] = build_dependency_graph(formulas, sheet_name)

    @property
    def source_type(self) -> SourceType:
        return SourceType.EXCEL

    # --- QueryableSource interface ---

    def execute_query(self, query: str, max_rows: int = 100) -> pd.DataFrame:
        return self._backend.execute_query(query, max_rows=max_rows)

    def get_sample(self, table_name: str, limit: int = 5) -> pd.DataFrame:
        return self._backend.execute_query(
            f'SELECT * FROM "{table_name}" LIMIT {limit}',
            max_rows=limit,
        )

    # --- Metadata ---

    def get_metadata(self) -> SourceMetadata:
        return SourceMetadata(
            source_id=self._source_id,
            source_type=SourceType.EXCEL,
            display_name=self._display_name,
            tables=self._tables,
            capabilities={"sql", "python", "formulas"},
            raw_info={
                "file_path": self._path,
                "sheets": self._reader.list_sheets(),
                "detected_tables": len(self._detected_tables),
            },
        )

    def get_context_description(self) -> str:
        """Rich context including tables, text regions, and formula intelligence."""
        lines = [
            f"Excel Workbook: {self._display_name}",
            f"Source ID: {self._source_id}",
        ]

        # --- Sheet overview ---
        lines.append(f"\nSheets ({len(self._reader.sheet_names)}):")
        for sheet_name in self._reader.sheet_names:
            analysis = self._sheet_analysis.get(sheet_name, {})
            stype = analysis.get("structure_type", "unknown")
            ntables = len(analysis.get("tables", []))
            ntext = len(analysis.get("text_regions", []))
            nformulas = len(self._formula_cache.get(sheet_name, []))
            parts = [f"type: {stype}", f"{ntables} table(s)"]
            if ntext:
                parts.append(f"{ntext} text region(s)")
            if nformulas:
                parts.append(f"{nformulas} formula(s)")
            lines.append(f"  - {sheet_name} ({', '.join(parts)})")

        # --- Extracted tables (queryable via SQL) ---
        if self._tables:
            lines.append(f"\nQueryable Tables ({len(self._tables)}):")
            for t in self._tables:
                lines.append(f"  - {t.name} ({t.row_count} rows)")
                for col in t.columns:
                    lines.append(f"      {col.name}: {col.dtype}")

        # --- Text regions (non-tabular context) ---
        text_sections = []
        for sheet_name in self._reader.sheet_names:
            analysis = self._sheet_analysis.get(sheet_name, {})
            for region in analysis.get("text_regions", []):
                text_sections.append((sheet_name, region))

        if text_sections:
            lines.append(f"\nText Context ({len(text_sections)} region(s)):")
            for sheet_name, region in text_sections:
                preview = region.text[:300].replace("\n", " | ")
                lines.append(
                    f"  - [{sheet_name}] rows {region.start_row + 1}-{region.end_row + 1}: "
                    f"{preview}"
                )

        # --- Formula intelligence ---
        all_clusters = []
        for sheet_name in self._reader.sheet_names:
            clusters = self._cluster_cache.get(sheet_name, [])
            for cluster in clusters:
                all_clusters.append((sheet_name, cluster))

        if all_clusters:
            lines.append(f"\nBusiness Logic (from formulas):")
            for sheet_name, cluster in all_clusters[:15]:  # Cap at 15 most important
                lines.append(
                    f"  - [{sheet_name}] {cluster.description} "
                    f"(pattern: {cluster.pattern}, {cluster.count} cells, "
                    f"e.g. {cluster.example})"
                )

        # Cross-sheet dependencies
        cross_sheet_refs = []
        for sheet_name in self._reader.sheet_names:
            for formula_rec in self._formula_cache.get(sheet_name, []):
                formula = formula_rec["formula"]
                # Detect cross-sheet references (contains "!" but not in function names)
                if "!" in formula and not formula.startswith("=!"):
                    cross_sheet_refs.append((sheet_name, formula_rec["cell"], formula))

        if cross_sheet_refs:
            lines.append(f"\nCross-Sheet References ({len(cross_sheet_refs)}):")
            for sheet, cell, formula in cross_sheet_refs[:10]:
                lines.append(f"  - [{sheet}]{cell}: {formula}")

        lines.append("\nExtracted tables can be queried with SQL via DuckDB.")
        return "\n".join(lines)

    # --- SpreadsheetSource interface ---

    def list_sheets(self) -> list[dict]:
        sheets = self._reader.list_sheets()
        for sheet in sheets:
            analysis = self._sheet_analysis.get(sheet["name"], {})
            sheet["structure_type"] = analysis.get("structure_type", "unknown")
            sheet["tables"] = len(analysis.get("tables", []))
            sheet["text_regions"] = len(analysis.get("text_regions", []))
        return sheets

    def read_range(
        self,
        sheet: str,
        range_str: str | None = None,
        include_formulas: bool = False,
    ) -> Any:
        grid = self._reader.read_range(sheet, range_str, include_formulas)
        return grid.to_text()

    def get_sheet_structure(self, sheet: str) -> Any:
        analysis = self._sheet_analysis.get(sheet)
        if analysis is None:
            raise ValueError(f"Sheet '{sheet}' not found")

        lines = [f"## Sheet: {sheet}"]
        lines.append(f"Structure: {analysis['structure_type']}")

        for table in analysis["tables"]:
            lines.append(f"\nTable: {table.range_str}")
            lines.append(f"  Headers: {', '.join(table.headers)}")
            lines.append(f"  Rows: {table.row_count}")

        for region in analysis["text_regions"]:
            lines.append(f"\nText region (rows {region.start_row + 1}-{region.end_row + 1}):")
            lines.append(f"  {region.text[:200]}")

        return "\n".join(lines)

    def extract_table(self, sheet: str, table_range: str) -> pd.DataFrame:
        grid = self._reader.read_range(sheet, table_range)
        if grid.row_count == 0:
            return pd.DataFrame()

        # First row as headers
        headers = [grid.get(0, c).display or f"col_{c}" for c in range(grid.col_count)]
        rows = []
        for r in range(1, grid.row_count):
            rows.append([grid.get(r, c).value for c in range(grid.col_count)])

        return pd.DataFrame(rows, columns=headers)

    def get_formulas(self, sheet_name: str) -> list[dict[str, str]]:
        """List all formulas in a sheet."""
        return self._formula_cache.get(sheet_name, [])

    def close(self) -> None:
        if not self._closed:
            self._reader.close()
            self._backend.close()
            self._closed = True
