"""Cell grid data structures for Excel representation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CellValue:
    """A single cell's data."""

    value: Any = None
    formula: str | None = None
    dtype: str = "text"  # text, number, date, bool, formula, empty

    @property
    def display(self) -> str:
        if self.value is None:
            return ""
        return str(self.value)


@dataclass
class MergedRegion:
    """A merged cell region."""

    min_row: int
    min_col: int
    max_row: int
    max_col: int

    @property
    def size(self) -> tuple[int, int]:
        return (self.max_row - self.min_row + 1, self.max_col - self.min_col + 1)


@dataclass
class CellGrid:
    """2D grid of cell values with optional merged regions."""

    cells: list[list[CellValue]] = field(default_factory=list)
    merged_regions: list[MergedRegion] = field(default_factory=list)
    row_count: int = 0
    col_count: int = 0

    def get(self, row: int, col: int) -> CellValue:
        """Get cell at (row, col), 0-indexed."""
        if 0 <= row < self.row_count and 0 <= col < self.col_count:
            return self.cells[row][col]
        return CellValue()

    def to_text(self, max_rows: int = 50, max_cols: int = 20) -> str:
        """Render the grid as formatted text for LLM consumption."""
        if not self.cells:
            return "(empty)"

        rows_to_show = min(self.row_count, max_rows)
        cols_to_show = min(self.col_count, max_cols)

        # Calculate column widths
        widths = [0] * cols_to_show
        for r in range(rows_to_show):
            for c in range(cols_to_show):
                val = self.cells[r][c].display
                widths[c] = max(widths[c], min(len(val), 30))

        # Minimum width
        widths = [max(w, 3) for w in widths]

        lines = []
        for r in range(rows_to_show):
            parts = []
            for c in range(cols_to_show):
                val = self.cells[r][c].display
                if len(val) > 30:
                    val = val[:27] + "..."
                parts.append(val.ljust(widths[c]))
            lines.append(" | ".join(parts))

        if self.row_count > max_rows:
            lines.append(f"... ({self.row_count - max_rows} more rows)")
        if self.col_count > max_cols:
            lines[0] += f" | ... ({self.col_count - max_cols} more cols)"

        return "\n".join(lines)

    @classmethod
    def from_worksheet(cls, ws: Any, data_only: bool = True) -> CellGrid:
        """Build a CellGrid from an openpyxl worksheet."""
        if ws.max_row is None or ws.max_column is None:
            return cls()

        row_count = ws.max_row
        col_count = ws.max_column

        cells: list[list[CellValue]] = []
        for row in ws.iter_rows(min_row=1, max_row=row_count, max_col=col_count):
            row_cells = []
            for cell in row:
                cv = CellValue(
                    value=cell.value,
                    dtype=_classify_cell_type(cell.value),
                )
                row_cells.append(cv)
            cells.append(row_cells)

        merged = []
        if hasattr(ws, "merged_cells") and ws.merged_cells:
            merged = [
                MergedRegion(
                    min_row=m.min_row - 1,  # 0-index
                    min_col=m.min_col - 1,
                    max_row=m.max_row - 1,
                    max_col=m.max_col - 1,
                )
                for m in ws.merged_cells.ranges
            ]

        return cls(
            cells=cells,
            merged_regions=merged,
            row_count=row_count,
            col_count=col_count,
        )


def _classify_cell_type(value: Any) -> str:
    """Classify a cell value's type."""
    if value is None:
        return "empty"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        if value.startswith("="):
            return "formula"
        return "text"
    # datetime, etc.
    return "text"
