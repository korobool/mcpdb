"""Multi-workbook support — manage multiple Excel files in one session."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mcpdb.sources.excel.source import ExcelSource

logger = logging.getLogger("mcpdb.excel.multi_workbook")


class MultiWorkbookManager:
    """Manage multiple Excel workbooks in a single session.

    Provides cross-workbook access using {workbook}::{sheet} notation.
    """

    def __init__(self, memory_limit: str = "2GB") -> None:
        self._workbooks: dict[str, ExcelSource] = {}
        self._memory_limit = memory_limit

    def load(self, file_path: str, name: str | None = None) -> str:
        """Load a workbook and return its reference name."""
        if name is None:
            name = Path(file_path).stem
        name = _sanitize_name(name)

        if name in self._workbooks:
            raise ValueError(f"Workbook '{name}' already loaded. Remove it first.")

        source = ExcelSource(file_path, display_name=name, memory_limit=self._memory_limit)
        self._workbooks[name] = source
        logger.info("Loaded workbook '%s' from %s", name, file_path)
        return name

    def remove(self, name: str) -> None:
        """Remove a loaded workbook."""
        source = self._workbooks.pop(name, None)
        if source is None:
            raise KeyError(f"Workbook '{name}' not found")
        source.close()

    def get(self, name: str) -> ExcelSource:
        """Get a workbook by name."""
        source = self._workbooks.get(name)
        if source is None:
            raise KeyError(f"Workbook '{name}' not found")
        return source

    def list_workbooks(self) -> list[dict[str, Any]]:
        """List all loaded workbooks."""
        result = []
        for name, source in self._workbooks.items():
            meta = source.get_metadata()
            sheets = source.list_sheets()
            result.append({
                "name": name,
                "source_id": meta.source_id,
                "sheets": len(sheets),
                "tables": len(meta.tables),
            })
        return result

    def resolve_reference(self, ref: str) -> tuple[ExcelSource, str]:
        """Resolve a cross-workbook reference like 'budget::Sheet1'.

        Returns (source, sheet_name) tuple.
        """
        if "::" in ref:
            workbook_name, sheet_name = ref.split("::", 1)
            source = self.get(workbook_name)
            return source, sheet_name
        else:
            # Try to find the sheet in any workbook
            for name, source in self._workbooks.items():
                sheets = source.list_sheets()
                for sheet in sheets:
                    if sheet["name"] == ref:
                        return source, ref
            raise KeyError(f"Sheet '{ref}' not found in any workbook")

    def read_cross_reference(
        self, ref: str, include_formulas: bool = False
    ) -> str:
        """Read a cross-workbook cell range.

        Format: 'workbook::Sheet1!A1:D10' or 'workbook::Sheet1'
        """
        if "::" not in ref:
            raise ValueError(
                "Cross-reference must use 'workbook::sheet' format"
            )

        workbook_name, rest = ref.split("::", 1)

        if "!" in rest:
            sheet_name, range_str = rest.split("!", 1)
        else:
            sheet_name = rest
            range_str = None

        source = self.get(workbook_name)
        return source.read_range(sheet_name, range_str, include_formulas)

    def get_all_tables(self) -> list[dict[str, Any]]:
        """Get all extracted tables across all workbooks."""
        tables = []
        for name, source in self._workbooks.items():
            meta = source.get_metadata()
            for table in meta.tables:
                tables.append({
                    "workbook": name,
                    "table_name": table.name,
                    "row_count": table.row_count,
                    "columns": [c.name for c in table.columns],
                })
        return tables

    def close_all(self) -> None:
        """Close all workbooks."""
        for source in self._workbooks.values():
            source.close()
        self._workbooks.clear()

    def __len__(self) -> int:
        return len(self._workbooks)

    def __contains__(self, name: str) -> bool:
        return name in self._workbooks


def _sanitize_name(name: str) -> str:
    """Sanitize a workbook name for use as a reference."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name).strip("_")
