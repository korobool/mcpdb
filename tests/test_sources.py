"""Tests for v0.0.2 — data source abstractions."""

from __future__ import annotations

import json

import pytest

from mcpdb.sources.base import (
    ColumnInfo,
    DataSource,
    QueryableSource,
    SourceMetadata,
    SourceType,
    SpreadsheetSource,
    TableInfo,
)
from mcpdb.sources.registry import SourceNotFoundError, SourceRegistry


# --- Mock implementations for testing ---


class MockDatabaseSource(QueryableSource):
    def __init__(self, source_id: str = "db_1", display_name: str = "Test DB"):
        self._source_id = source_id
        self._display_name = display_name
        self._closed = False

    @property
    def source_type(self) -> SourceType:
        return SourceType.DATABASE

    def get_metadata(self) -> SourceMetadata:
        return SourceMetadata(
            source_id=self._source_id,
            source_type=SourceType.DATABASE,
            display_name=self._display_name,
            tables=[
                TableInfo(
                    name="customers",
                    columns=[
                        ColumnInfo(name="id", dtype="INTEGER", nullable=False),
                        ColumnInfo(name="name", dtype="VARCHAR"),
                    ],
                    row_count=100,
                    primary_keys=["id"],
                ),
            ],
            capabilities={"sql", "python"},
        )

    def get_context_description(self) -> str:
        return f"Database: {self._display_name} (1 table)"

    def execute_query(self, query: str, max_rows: int = 100):
        raise NotImplementedError("Mock")

    def get_sample(self, table_name: str, limit: int = 5):
        raise NotImplementedError("Mock")

    def close(self) -> None:
        self._closed = True


class MockExcelSource(SpreadsheetSource):
    def __init__(self, source_id: str = "excel_1"):
        self._source_id = source_id
        self._closed = False

    @property
    def source_type(self) -> SourceType:
        return SourceType.EXCEL

    def get_metadata(self) -> SourceMetadata:
        return SourceMetadata(
            source_id=self._source_id,
            source_type=SourceType.EXCEL,
            display_name="Test Workbook",
            tables=[],
            capabilities={"formulas"},
        )

    def get_context_description(self) -> str:
        return "Excel: Test Workbook"

    def list_sheets(self) -> list[dict]:
        return [{"name": "Sheet1"}]

    def read_range(self, sheet, range_str=None, include_formulas=False):
        raise NotImplementedError("Mock")

    def get_sheet_structure(self, sheet):
        raise NotImplementedError("Mock")

    def extract_table(self, sheet, table_range):
        raise NotImplementedError("Mock")

    def close(self) -> None:
        self._closed = True


# --- DataSource / metadata tests ---


class TestSourceMetadata:
    def test_source_type_enum(self):
        assert SourceType.DATABASE.value == "database"
        assert SourceType.CSV.value == "csv"
        assert SourceType.EXCEL.value == "excel"

    def test_column_info(self):
        col = ColumnInfo(name="id", dtype="INTEGER", nullable=False)
        assert col.name == "id"
        assert col.nullable is False

    def test_table_info_defaults(self):
        t = TableInfo(name="t", columns=[])
        assert t.row_count is None
        assert t.primary_keys == []
        assert t.indexes == []

    def test_source_metadata_to_dict(self):
        meta = SourceMetadata(
            source_id="x",
            source_type=SourceType.DATABASE,
            display_name="X",
            tables=[],
            capabilities={"sql", "python"},
        )
        d = meta.to_dict()
        assert d["source_type"] == "database"
        assert d["capabilities"] == ["python", "sql"]  # sorted

    def test_get_schema_json(self):
        src = MockDatabaseSource()
        schema = src.get_schema_json()
        parsed = json.loads(schema)
        assert parsed["source_id"] == "db_1"
        assert len(parsed["tables"]) == 1

    def test_get_tables(self):
        src = MockDatabaseSource()
        tables = src.get_tables()
        assert len(tables) == 1
        assert tables[0].name == "customers"


# --- SourceRegistry tests ---


class TestSourceRegistry:
    def test_add_and_get(self):
        reg = SourceRegistry()
        src = MockDatabaseSource()
        sid = reg.add_source(src)
        assert sid == "db_1"
        assert reg.get_source("db_1") is src

    def test_add_duplicate_raises(self):
        reg = SourceRegistry()
        reg.add_source(MockDatabaseSource())
        with pytest.raises(ValueError, match="already exists"):
            reg.add_source(MockDatabaseSource())

    def test_remove_source(self):
        reg = SourceRegistry()
        src = MockDatabaseSource()
        reg.add_source(src)
        reg.remove_source("db_1")
        assert src._closed
        assert len(reg) == 0

    def test_remove_nonexistent_raises(self):
        reg = SourceRegistry()
        with pytest.raises(SourceNotFoundError):
            reg.remove_source("nope")

    def test_get_nonexistent_raises(self):
        reg = SourceRegistry()
        with pytest.raises(SourceNotFoundError):
            reg.get_source("nope")

    def test_list_sources(self):
        reg = SourceRegistry()
        reg.add_source(MockDatabaseSource("db_1"))
        reg.add_source(MockExcelSource("excel_1"))
        metas = reg.list_sources()
        assert len(metas) == 2
        ids = {m.source_id for m in metas}
        assert ids == {"db_1", "excel_1"}

    def test_contains(self):
        reg = SourceRegistry()
        reg.add_source(MockDatabaseSource())
        assert "db_1" in reg
        assert "nope" not in reg

    def test_get_queryable_sources(self):
        reg = SourceRegistry()
        reg.add_source(MockDatabaseSource())
        reg.add_source(MockExcelSource())
        qs = reg.get_queryable_sources()
        assert len(qs) == 1
        assert isinstance(qs[0], QueryableSource)

    def test_get_spreadsheet_sources(self):
        reg = SourceRegistry()
        reg.add_source(MockDatabaseSource())
        reg.add_source(MockExcelSource())
        ss = reg.get_spreadsheet_sources()
        assert len(ss) == 1
        assert isinstance(ss[0], SpreadsheetSource)

    def test_combined_context_empty(self):
        reg = SourceRegistry()
        assert reg.get_combined_context() == "No data sources connected."

    def test_combined_context(self):
        reg = SourceRegistry()
        reg.add_source(MockDatabaseSource())
        ctx = reg.get_combined_context()
        assert "Test DB" in ctx
        assert "Database: Test DB" in ctx

    def test_close_all(self):
        reg = SourceRegistry()
        s1 = MockDatabaseSource("db_1")
        s2 = MockExcelSource("excel_1")
        reg.add_source(s1)
        reg.add_source(s2)
        reg.close_all()
        assert s1._closed
        assert s2._closed
        assert len(reg) == 0
