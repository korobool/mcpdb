"""Structure analyzer — detect tables vs text regions in Excel sheets."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from mcpdb.sources.excel.cell_grid import CellGrid

logger = logging.getLogger("mcpdb.excel.analyzer")


@dataclass
class DetectedTable:
    """A region identified as tabular data (Case 1)."""

    sheet_name: str
    header_row: int  # 0-indexed
    data_start_row: int
    data_end_row: int
    start_col: int
    end_col: int
    headers: list[str]
    row_count: int

    @property
    def range_str(self) -> str:
        """Return Excel-style range string (1-indexed)."""
        from openpyxl.utils import get_column_letter
        start = f"{get_column_letter(self.start_col + 1)}{self.header_row + 1}"
        end = f"{get_column_letter(self.end_col + 1)}{self.data_end_row + 1}"
        return f"{start}:{end}"


@dataclass
class TextRegion:
    """A region identified as unstructured text (Case 2)."""

    sheet_name: str
    start_row: int
    end_row: int
    start_col: int
    end_col: int
    text: str


def analyze_sheet(grid: CellGrid, sheet_name: str) -> dict[str, Any]:
    """Analyze a sheet's structure.

    Returns dict with:
    - tables: list[DetectedTable]
    - text_regions: list[TextRegion]
    - structure_type: "table" | "mixed" | "text"
    """
    if grid.row_count == 0 or grid.col_count == 0:
        return {"tables": [], "text_regions": [], "structure_type": "empty"}

    tables = _detect_tables(grid, sheet_name)
    text_regions = _detect_text_regions(grid, sheet_name, tables)

    if tables and not text_regions:
        stype = "table"
    elif not tables:
        stype = "text"
    else:
        stype = "mixed"

    return {
        "tables": tables,
        "text_regions": text_regions,
        "structure_type": stype,
    }


def _detect_tables(grid: CellGrid, sheet_name: str) -> list[DetectedTable]:
    """Detect table regions using header-row heuristic.

    A table is detected when a row has multiple non-empty text cells followed
    by rows with data of consistent width.
    """
    tables: list[DetectedTable] = []

    row = 0
    while row < grid.row_count:
        # Check if this row looks like a header
        header_cols = _find_header_row(grid, row)
        if header_cols is not None:
            start_col, end_col, headers = header_cols

            # Count data rows below
            data_start = row + 1
            data_end = data_start
            while data_end < grid.row_count:
                # Check if this row has data in the expected columns
                non_empty = sum(
                    1 for c in range(start_col, end_col + 1)
                    if grid.get(data_end, c).value is not None
                )
                if non_empty < len(headers) * 0.3:  # Less than 30% filled → end of table
                    break
                data_end += 1

            if data_end > data_start:  # At least one data row
                tables.append(DetectedTable(
                    sheet_name=sheet_name,
                    header_row=row,
                    data_start_row=data_start,
                    data_end_row=data_end - 1,
                    start_col=start_col,
                    end_col=end_col,
                    headers=headers,
                    row_count=data_end - data_start,
                ))
                row = data_end
                continue

        row += 1

    return tables


def _find_header_row(
    grid: CellGrid, row: int
) -> tuple[int, int, list[str]] | None:
    """Check if a row looks like a table header.

    Returns (start_col, end_col, headers) or None.
    """
    if row >= grid.row_count:
        return None

    # Collect non-empty text cells
    text_cells = []
    for c in range(grid.col_count):
        cell = grid.get(row, c)
        if cell.value is not None and isinstance(cell.value, str) and cell.value.strip():
            text_cells.append((c, cell.value.strip()))

    # Need at least 2 text cells for a header
    if len(text_cells) < 2:
        return None

    # Check that they're roughly consecutive (gaps of at most 1)
    cols = [t[0] for t in text_cells]
    max_gap = max(cols[i + 1] - cols[i] for i in range(len(cols) - 1))
    if max_gap > 2:
        return None

    start_col = cols[0]
    end_col = cols[-1]
    headers = [t[1] for t in text_cells]

    # Verify the next row has data (not all empty)
    if row + 1 < grid.row_count:
        next_non_empty = sum(
            1 for c in range(start_col, end_col + 1)
            if grid.get(row + 1, c).value is not None
        )
        if next_non_empty == 0:
            return None

    return start_col, end_col, headers


def _detect_text_regions(
    grid: CellGrid, sheet_name: str, tables: list[DetectedTable]
) -> list[TextRegion]:
    """Find non-table regions that contain text."""
    # Build a set of rows occupied by tables
    table_rows: set[int] = set()
    for table in tables:
        for r in range(table.header_row, table.data_end_row + 1):
            table_rows.add(r)

    text_regions: list[TextRegion] = []
    current_text: list[str] = []
    region_start = None

    for r in range(grid.row_count):
        if r in table_rows:
            # Flush any accumulated text
            if current_text and region_start is not None:
                text_regions.append(TextRegion(
                    sheet_name=sheet_name,
                    start_row=region_start,
                    end_row=r - 1,
                    start_col=0,
                    end_col=grid.col_count - 1,
                    text="\n".join(current_text),
                ))
                current_text = []
                region_start = None
            continue

        # Check if this row has any content
        row_text = []
        for c in range(grid.col_count):
            cell = grid.get(r, c)
            if cell.value is not None:
                row_text.append(str(cell.value))

        if row_text:
            if region_start is None:
                region_start = r
            current_text.append(" | ".join(row_text))

    # Flush remaining
    if current_text and region_start is not None:
        text_regions.append(TextRegion(
            sheet_name=sheet_name,
            start_row=region_start,
            end_row=grid.row_count - 1,
            start_col=0,
            end_col=grid.col_count - 1,
            text="\n".join(current_text),
        ))

    return text_regions
