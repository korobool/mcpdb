"""Formula cluster analysis — detect groups of similar formulas."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("mcpdb.excel.formula_clusters")


@dataclass
class FormulaCluster:
    """A group of similar formulas."""

    pattern: str  # Generalized pattern (e.g., "=A{row}*B{row}")
    cells: list[str]  # Cells using this pattern (e.g., ["C1", "C2", "C3"])
    example: str  # One concrete formula
    description: str = ""  # Human-readable description
    count: int = 0


def find_formula_clusters(
    formulas: list[dict[str, str]],
    min_cluster_size: int = 2,
) -> list[FormulaCluster]:
    """Detect groups of similar formulas.

    Formulas are generalized by replacing row numbers with placeholders,
    then grouped by their generalized pattern.
    """
    # Group formulas by their generalized pattern
    pattern_groups: dict[str, list[tuple[str, str]]] = {}

    for f_rec in formulas:
        cell = f_rec["cell"]
        formula = f_rec["formula"]
        pattern = _generalize_formula(formula, cell)
        if pattern not in pattern_groups:
            pattern_groups[pattern] = []
        pattern_groups[pattern].append((cell, formula))

    # Build clusters
    clusters = []
    for pattern, members in pattern_groups.items():
        if len(members) >= min_cluster_size:
            cluster = FormulaCluster(
                pattern=pattern,
                cells=[m[0] for m in members],
                example=members[0][1],
                count=len(members),
                description=_describe_pattern(pattern, members),
            )
            clusters.append(cluster)

    # Sort by size (largest first)
    clusters.sort(key=lambda c: c.count, reverse=True)
    return clusters


def _generalize_formula(formula: str, cell: str) -> str:
    """Generalize a formula by replacing row numbers with {row} placeholder.

    E.g., "=A1*B1" in cell C1 → "=A{row}*B{row}"
    """
    if not formula:
        return formula

    # Extract row number from the cell reference
    _, row_str = _split_cell(cell)
    if not row_str:
        return formula

    # Replace row number in cell references
    # Match patterns like A1, $B$2, etc. and replace the row part
    def replace_row(match: re.Match) -> str:
        prefix = match.group(1)  # column part
        row = match.group(2)     # row number
        if row == row_str:
            return f"{prefix}{{row}}"
        return match.group(0)

    pattern = re.sub(
        r"(\$?[A-Z]{1,3})\$?(\d+)",
        replace_row,
        formula,
    )
    return pattern


def _describe_pattern(pattern: str, members: list[tuple[str, str]]) -> str:
    """Generate a human-readable description of a formula pattern."""
    cells = [m[0] for m in members]
    col = _common_column(cells)

    # Detect common functions
    func_match = re.match(r"=([A-Z]+)\(", pattern)
    if func_match:
        func_name = func_match.group(1)
        if col:
            return f"Column {col} applies {func_name} across each row"
        return f"Each cell applies {func_name}"

    # Simple arithmetic
    if "+" in pattern or "-" in pattern or "*" in pattern or "/" in pattern:
        if col:
            return f"Column {col} computes a formula for each row"
        return "Each cell computes an arithmetic formula"

    if col:
        return f"Column {col} has {len(members)} cells with the same formula pattern"
    return f"{len(members)} cells share the same formula pattern"


def _split_cell(ref: str) -> tuple[str, str]:
    """Split cell reference into column and row parts."""
    ref = ref.replace("$", "")
    col = ""
    row = ""
    for ch in ref:
        if ch.isalpha():
            col += ch
        else:
            row += ch
    return col, row


def _common_column(cells: list[str]) -> str:
    """Find the common column among cell references, or empty string."""
    cols = set()
    for cell in cells:
        col, _ = _split_cell(cell)
        cols.add(col)
    if len(cols) == 1:
        return cols.pop()
    return ""
