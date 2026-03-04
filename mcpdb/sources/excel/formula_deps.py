"""Formula dependency graph — trace upstream/downstream cell references."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("mcpdb.excel.formula_deps")

# Regex to find cell references like A1, $B$2, Sheet1!C3, etc.
_CELL_REF_RE = re.compile(
    r"(?:(?P<sheet>[A-Za-z_]\w*)\!)?"  # optional sheet name with !
    r"(?P<ref>\$?[A-Z]{1,3}\$?\d+)"    # column + row (e.g., A1, $B$2)
)

# Regex to find range references like A1:B10
_RANGE_REF_RE = re.compile(
    r"(?:(?P<sheet>[A-Za-z_]\w*)\!)?"
    r"(?P<start>\$?[A-Z]{1,3}\$?\d+)"
    r":"
    r"(?P<end>\$?[A-Z]{1,3}\$?\d+)"
)


@dataclass
class CellDependency:
    """A single dependency relationship between cells."""

    source_cell: str  # e.g., "A1"
    source_sheet: str
    target_cell: str  # The cell that depends on source
    target_sheet: str


@dataclass
class DependencyGraph:
    """Full dependency graph for a sheet or workbook."""

    # cell_ref → list of cells it depends on (upstream)
    upstream: dict[str, list[str]] = field(default_factory=dict)
    # cell_ref → list of cells that depend on it (downstream)
    downstream: dict[str, list[str]] = field(default_factory=dict)
    # All edges
    edges: list[CellDependency] = field(default_factory=list)

    def get_upstream(self, cell: str) -> list[str]:
        """Get cells that this cell depends on."""
        return self.upstream.get(cell.upper(), [])

    def get_downstream(self, cell: str) -> list[str]:
        """Get cells that depend on this cell."""
        return self.downstream.get(cell.upper(), [])

    def get_all_cells(self) -> set[str]:
        """Get all cells involved in any dependency."""
        cells = set()
        cells.update(self.upstream.keys())
        cells.update(self.downstream.keys())
        return cells

    def to_mermaid(self, max_nodes: int = 50) -> str:
        """Render as a Mermaid flowchart."""
        lines = ["graph LR"]
        seen = set()
        for edge in self.edges[:max_nodes]:
            key = f"{edge.source_cell}->{edge.target_cell}"
            if key not in seen:
                seen.add(key)
                lines.append(f"    {edge.source_cell} --> {edge.target_cell}")
        return "\n".join(lines)


def parse_formula_references(formula: str, current_sheet: str = "") -> list[str]:
    """Extract all cell references from a formula string.

    Returns list of cell references (e.g., ["A1", "B2", "C3:C10"]).
    """
    if not formula or not formula.startswith("="):
        return []

    refs = []

    # Find range references first (to avoid double-counting)
    range_spans = set()
    for match in _RANGE_REF_RE.finditer(formula):
        start = match.group("start").replace("$", "")
        end = match.group("end").replace("$", "")
        refs.append(f"{start}:{end}")
        range_spans.add((match.start(), match.end()))

    # Find individual cell references not part of ranges
    for match in _CELL_REF_RE.finditer(formula):
        pos = match.start()
        in_range = any(s <= pos < e for s, e in range_spans)
        if not in_range:
            ref = match.group("ref").replace("$", "")
            refs.append(ref)

    return refs


def expand_range(range_ref: str) -> list[str]:
    """Expand a range reference like A1:A5 into individual cells.

    Returns list of cell references.
    """
    if ":" not in range_ref:
        return [range_ref]

    start, end = range_ref.split(":")
    start_col, start_row = _split_cell_ref(start)
    end_col, end_row = _split_cell_ref(end)

    cells = []
    for col_idx in range(_col_to_num(start_col), _col_to_num(end_col) + 1):
        for row in range(start_row, end_row + 1):
            cells.append(f"{_num_to_col(col_idx)}{row}")
    return cells


def build_dependency_graph(
    formulas: list[dict[str, str]],
    sheet_name: str = "Sheet1",
) -> DependencyGraph:
    """Build a dependency graph from a list of formula records.

    Each formula record is {"cell": "C1", "formula": "=A1+B1"}.
    """
    graph = DependencyGraph()

    for f_rec in formulas:
        target = f_rec["cell"].upper()
        formula = f_rec["formula"]
        refs = parse_formula_references(formula, sheet_name)

        upstream_cells = []
        for ref in refs:
            if ":" in ref:
                expanded = expand_range(ref)
                upstream_cells.extend(expanded)
            else:
                upstream_cells.append(ref.upper())

        # Record upstream
        graph.upstream[target] = upstream_cells

        # Record downstream
        for src in upstream_cells:
            if src not in graph.downstream:
                graph.downstream[src] = []
            graph.downstream[src].append(target)

        # Record edges
        for src in upstream_cells:
            graph.edges.append(CellDependency(
                source_cell=src,
                source_sheet=sheet_name,
                target_cell=target,
                target_sheet=sheet_name,
            ))

    return graph


def _split_cell_ref(ref: str) -> tuple[str, int]:
    """Split a cell reference into column letters and row number."""
    ref = ref.replace("$", "")
    col = ""
    row = ""
    for ch in ref:
        if ch.isalpha():
            col += ch
        else:
            row += ch
    return col.upper(), int(row) if row else 1


def _col_to_num(col: str) -> int:
    """Convert column letters to number (A=1, B=2, ..., Z=26, AA=27)."""
    result = 0
    for ch in col.upper():
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result


def _num_to_col(num: int) -> str:
    """Convert column number to letters."""
    result = ""
    while num > 0:
        num, remainder = divmod(num - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result
