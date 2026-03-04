"""Tests for v3.4.x — Excel Advanced (formula deps, cluster analysis, multi-workbook)."""

from __future__ import annotations

import pytest

from mcpdb.sources.excel.formula_deps import (
    CellDependency,
    DependencyGraph,
    build_dependency_graph,
    expand_range,
    parse_formula_references,
    _col_to_num,
    _num_to_col,
    _split_cell_ref,
)
from mcpdb.sources.excel.formula_clusters import (
    FormulaCluster,
    find_formula_clusters,
    _generalize_formula,
    _describe_pattern,
    _split_cell,
    _common_column,
)
from mcpdb.sources.excel.multi_workbook import (
    MultiWorkbookManager,
    _sanitize_name,
)


# ---------------------------------------------------------------------------
# Formula dependency parsing
# ---------------------------------------------------------------------------

class TestFormulaReferences:
    def test_simple_refs(self):
        refs = parse_formula_references("=A1+B1")
        assert "A1" in refs
        assert "B1" in refs

    def test_function_refs(self):
        refs = parse_formula_references("=SUM(A1:A10)")
        assert "A1:A10" in refs

    def test_mixed_refs_and_ranges(self):
        refs = parse_formula_references("=A1+SUM(B1:B10)+C1")
        assert "A1" in refs
        assert "B1:B10" in refs
        assert "C1" in refs

    def test_dollar_refs(self):
        refs = parse_formula_references("=$A$1+$B2")
        assert "A1" in refs
        assert "B2" in refs

    def test_empty_formula(self):
        assert parse_formula_references("") == []
        assert parse_formula_references("hello") == []

    def test_no_equals(self):
        assert parse_formula_references("A1+B1") == []


class TestExpandRange:
    def test_single_cell(self):
        assert expand_range("A1") == ["A1"]

    def test_single_column_range(self):
        cells = expand_range("A1:A3")
        assert cells == ["A1", "A2", "A3"]

    def test_single_row_range(self):
        cells = expand_range("A1:C1")
        assert cells == ["A1", "B1", "C1"]

    def test_rectangular_range(self):
        cells = expand_range("A1:B2")
        assert set(cells) == {"A1", "A2", "B1", "B2"}


class TestColConversion:
    def test_a_to_1(self):
        assert _col_to_num("A") == 1

    def test_z_to_26(self):
        assert _col_to_num("Z") == 26

    def test_aa_to_27(self):
        assert _col_to_num("AA") == 27

    def test_roundtrip(self):
        for i in range(1, 100):
            assert _col_to_num(_num_to_col(i)) == i


class TestSplitCellRef:
    def test_basic(self):
        col, row = _split_cell_ref("A1")
        assert col == "A"
        assert row == 1

    def test_multi_letter(self):
        col, row = _split_cell_ref("AB123")
        assert col == "AB"
        assert row == 123

    def test_dollar_signs(self):
        col, row = _split_cell_ref("$A$1")
        assert col == "A"
        assert row == 1


# ---------------------------------------------------------------------------
# Dependency graph building
# ---------------------------------------------------------------------------

class TestDependencyGraph:
    def test_simple_graph(self):
        formulas = [
            {"cell": "C1", "formula": "=A1+B1"},
            {"cell": "C2", "formula": "=A2+B2"},
        ]
        graph = build_dependency_graph(formulas)

        assert "A1" in graph.get_upstream("C1")
        assert "B1" in graph.get_upstream("C1")
        assert "C1" in graph.get_downstream("A1")
        assert len(graph.edges) == 4  # 2 deps × 2 formulas

    def test_sum_range(self):
        formulas = [
            {"cell": "B1", "formula": "=SUM(A1:A5)"},
        ]
        graph = build_dependency_graph(formulas)
        upstream = graph.get_upstream("B1")
        assert "A1" in upstream
        assert "A5" in upstream
        assert len(upstream) == 5

    def test_get_all_cells(self):
        formulas = [{"cell": "C1", "formula": "=A1+B1"}]
        graph = build_dependency_graph(formulas)
        cells = graph.get_all_cells()
        assert "A1" in cells
        assert "B1" in cells
        assert "C1" in cells

    def test_empty_graph(self):
        graph = build_dependency_graph([])
        assert graph.get_upstream("A1") == []
        assert graph.get_downstream("A1") == []
        assert graph.get_all_cells() == set()

    def test_mermaid_output(self):
        formulas = [{"cell": "C1", "formula": "=A1+B1"}]
        graph = build_dependency_graph(formulas)
        mermaid = graph.to_mermaid()
        assert "graph LR" in mermaid
        assert "-->" in mermaid


# ---------------------------------------------------------------------------
# Formula cluster analysis
# ---------------------------------------------------------------------------

class TestFormulaGeneralize:
    def test_same_row(self):
        result = _generalize_formula("=A1*B1", "C1")
        assert result == "=A{row}*B{row}"

    def test_different_row(self):
        result = _generalize_formula("=A2*B2", "C2")
        assert result == "=A{row}*B{row}"

    def test_fixed_reference(self):
        # Reference to row 1 in a cell on row 5 — should not generalize
        result = _generalize_formula("=A1*B5", "C5")
        assert "A1" in result  # row 1 stays
        assert "B{row}" in result  # row 5 generalized

    def test_empty(self):
        assert _generalize_formula("", "A1") == ""


class TestFormulaClusters:
    def test_basic_cluster(self):
        formulas = [
            {"cell": "C1", "formula": "=A1*B1"},
            {"cell": "C2", "formula": "=A2*B2"},
            {"cell": "C3", "formula": "=A3*B3"},
        ]
        clusters = find_formula_clusters(formulas)
        assert len(clusters) == 1
        assert clusters[0].count == 3
        assert "C1" in clusters[0].cells

    def test_min_cluster_size(self):
        formulas = [
            {"cell": "C1", "formula": "=A1*B1"},
        ]
        clusters = find_formula_clusters(formulas, min_cluster_size=2)
        assert len(clusters) == 0

    def test_multiple_clusters(self):
        formulas = [
            {"cell": "C1", "formula": "=A1+B1"},
            {"cell": "C2", "formula": "=A2+B2"},
            {"cell": "D1", "formula": "=SUM(A1:B1)"},
            {"cell": "D2", "formula": "=SUM(A2:B2)"},
        ]
        clusters = find_formula_clusters(formulas)
        assert len(clusters) == 2

    def test_description_has_function(self):
        # Both formulas have same pattern when row is generalized
        formulas = [
            {"cell": "C1", "formula": "=SUM(A1,B1)"},
            {"cell": "C2", "formula": "=SUM(A2,B2)"},
        ]
        clusters = find_formula_clusters(formulas)
        assert len(clusters) >= 1
        # At least one cluster should mention SUM
        descriptions = [c.description for c in clusters]
        assert any("SUM" in d for d in descriptions)


class TestSplitCell:
    def test_basic(self):
        assert _split_cell("A1") == ("A", "1")
        assert _split_cell("AB123") == ("AB", "123")
        assert _split_cell("$A$1") == ("A", "1")


class TestCommonColumn:
    def test_same_column(self):
        assert _common_column(["C1", "C2", "C3"]) == "C"

    def test_different_columns(self):
        assert _common_column(["A1", "B2"]) == ""

    def test_empty(self):
        assert _common_column([]) == ""


# ---------------------------------------------------------------------------
# Multi-workbook manager
# ---------------------------------------------------------------------------

class TestSanitizeName:
    def test_basic(self):
        assert _sanitize_name("budget") == "budget"

    def test_spaces(self):
        assert _sanitize_name("my budget") == "my_budget"

    def test_special_chars(self):
        assert _sanitize_name("file-v2.xlsx") == "file_v2_xlsx"

    def test_strip_underscores(self):
        assert _sanitize_name("__name__") == "name"


class TestMultiWorkbookManager:
    def test_init(self):
        mgr = MultiWorkbookManager()
        assert len(mgr) == 0

    def test_list_empty(self):
        mgr = MultiWorkbookManager()
        assert mgr.list_workbooks() == []

    def test_contains(self):
        mgr = MultiWorkbookManager()
        assert "test" not in mgr

    def test_get_missing(self):
        mgr = MultiWorkbookManager()
        with pytest.raises(KeyError):
            mgr.get("nonexistent")

    def test_remove_missing(self):
        mgr = MultiWorkbookManager()
        with pytest.raises(KeyError):
            mgr.remove("nonexistent")

    def test_resolve_reference_missing(self):
        mgr = MultiWorkbookManager()
        with pytest.raises(KeyError):
            mgr.resolve_reference("budget::Sheet1")

    def test_cross_reference_no_separator(self):
        mgr = MultiWorkbookManager()
        with pytest.raises(ValueError):
            mgr.read_cross_reference("Sheet1")

    def test_get_all_tables_empty(self):
        mgr = MultiWorkbookManager()
        assert mgr.get_all_tables() == []

    def test_close_all_empty(self):
        mgr = MultiWorkbookManager()
        mgr.close_all()  # should not raise


# ---------------------------------------------------------------------------
# Module import tests
# ---------------------------------------------------------------------------

class TestImports:
    def test_import_formula_deps(self):
        from mcpdb.sources.excel.formula_deps import (
            build_dependency_graph,
            parse_formula_references,
            expand_range,
            DependencyGraph,
            CellDependency,
        )
        assert callable(build_dependency_graph)

    def test_import_formula_clusters(self):
        from mcpdb.sources.excel.formula_clusters import (
            find_formula_clusters,
            FormulaCluster,
        )
        assert callable(find_formula_clusters)

    def test_import_multi_workbook(self):
        from mcpdb.sources.excel.multi_workbook import MultiWorkbookManager
        assert callable(MultiWorkbookManager)
