"""Tests for v3.3.x — Experience Advanced (strategy records, cross-dialect, schema drift, MCP tools)."""

from __future__ import annotations

import pytest

from mcpdb.sources.base import ColumnInfo, SourceMetadata, SourceType, TableInfo
from mcpdb.experience.store import ExperienceStore
from mcpdb.experience.fingerprint import fingerprint_source, fingerprint_schema


def _make_meta(tables=None, source_id="test_src") -> SourceMetadata:
    if tables is None:
        tables = [
            TableInfo(
                name="users",
                columns=[
                    ColumnInfo(name="id", dtype="int"),
                    ColumnInfo(name="name", dtype="str"),
                ],
            ),
        ]
    return SourceMetadata(
        source_id=source_id,
        source_type=SourceType.DATABASE,
        display_name="Test",
        tables=tables,
        capabilities={"query", "schema"},
    )


class _MockSource:
    """Minimal DataSource for registry tests."""

    def __init__(self, meta: SourceMetadata) -> None:
        self._meta = meta

    def get_metadata(self) -> SourceMetadata:
        return self._meta

    def get_context_description(self) -> str:
        return ""

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Strategy records
# ---------------------------------------------------------------------------

class TestStrategyRecords:
    def test_record_and_retrieve(self, tmp_path):
        from mcpdb.experience.strategy_records import StrategyTracker
        store = ExperienceStore(storage_dir=str(tmp_path))
        tracker = StrategyTracker(store)
        meta = _make_meta()

        tracker.record_strategy(
            meta, "SELECT * FROM users", 1_000_000, "SAMPLE", True, "good", 500.0
        )
        records = tracker.get_strategy_records(meta)
        assert len(records) == 1
        assert records[0].strategy == "SAMPLE"
        assert records[0].success is True
        assert records[0].result_quality == "good"

    def test_multiple_records(self, tmp_path):
        from mcpdb.experience.strategy_records import StrategyTracker
        store = ExperienceStore(storage_dir=str(tmp_path))
        tracker = StrategyTracker(store)
        meta = _make_meta()

        tracker.record_strategy(meta, "q1", 1000, "FULL", True)
        tracker.record_strategy(meta, "q2", 1000, "SAMPLE", True)
        tracker.record_strategy(meta, "q3", 1000, "FULL", True)

        records = tracker.get_strategy_records(meta)
        assert len(records) == 3

    def test_suggest_no_records(self, tmp_path):
        from mcpdb.experience.strategy_records import StrategyTracker
        store = ExperienceStore(storage_dir=str(tmp_path))
        tracker = StrategyTracker(store)
        meta = _make_meta()

        assert tracker.suggest_strategy(meta, "q1", 1000) is None

    def test_suggest_needs_threshold(self, tmp_path):
        from mcpdb.experience.strategy_records import StrategyTracker
        store = ExperienceStore(storage_dir=str(tmp_path))
        tracker = StrategyTracker(store)
        meta = _make_meta()

        # Only 1 record — not enough
        tracker.record_strategy(meta, "q1", 500_000, "SAMPLE", True, "good")
        assert tracker.suggest_strategy(meta, "q1", 500_000) is None

    def test_suggest_with_enough_records(self, tmp_path):
        from mcpdb.experience.strategy_records import StrategyTracker
        store = ExperienceStore(storage_dir=str(tmp_path))
        tracker = StrategyTracker(store)
        meta = _make_meta()

        # 2 SAMPLE successes at same magnitude
        tracker.record_strategy(meta, "q1", 500_000, "SAMPLE", True, "good")
        tracker.record_strategy(meta, "q2", 600_000, "SAMPLE", True, "good")

        suggestion = tracker.suggest_strategy(meta, "q3", 500_000)
        assert suggestion == "SAMPLE"

    def test_suggest_rejects_poor_quality(self, tmp_path):
        from mcpdb.experience.strategy_records import StrategyTracker
        store = ExperienceStore(storage_dir=str(tmp_path))
        tracker = StrategyTracker(store)
        meta = _make_meta()

        tracker.record_strategy(meta, "q1", 500_000, "SAMPLE", True, "poor")
        tracker.record_strategy(meta, "q2", 600_000, "SAMPLE", True, "poor")

        assert tracker.suggest_strategy(meta, "q3", 500_000) is None

    def test_strategy_context(self, tmp_path):
        from mcpdb.experience.strategy_records import StrategyTracker
        store = ExperienceStore(storage_dir=str(tmp_path))
        tracker = StrategyTracker(store)
        meta = _make_meta()

        tracker.record_strategy(meta, "q1", 500_000, "SAMPLE", True, "good")
        tracker.record_strategy(meta, "q2", 600_000, "SAMPLE", True, "good")

        ctx = tracker.get_strategy_context(meta, "q3", 500_000)
        assert ctx is not None
        assert "SAMPLE" in ctx

    def test_strategy_context_no_suggestion(self, tmp_path):
        from mcpdb.experience.strategy_records import StrategyTracker
        store = ExperienceStore(storage_dir=str(tmp_path))
        tracker = StrategyTracker(store)
        meta = _make_meta()

        assert tracker.get_strategy_context(meta, "q1", 100) is None

    def test_row_magnitude(self):
        from mcpdb.experience.strategy_records import _row_magnitude
        assert _row_magnitude(500) == "small"
        assert _row_magnitude(50_000) == "medium"
        assert _row_magnitude(5_000_000) == "large"
        assert _row_magnitude(50_000_000) == "very_large"


# ---------------------------------------------------------------------------
# Cross-dialect knowledge transfer
# ---------------------------------------------------------------------------

class TestCrossDialect:
    def test_single_source_no_promotion(self):
        from mcpdb.experience.cross_dialect import CrossDialectKnowledge
        store = ExperienceStore.__new__(ExperienceStore)
        store._storage_dir = "/tmp"
        store._lock = __import__("threading").Lock()

        kb = CrossDialectKnowledge(store, promotion_threshold=2)
        kb.record_pattern("postgresql", "fp1", "quote_identifiers",
                          "Always quote mixed-case identifiers")

        assert kb.get_patterns("postgresql") == []

    def test_promotion_at_threshold(self):
        from mcpdb.experience.cross_dialect import CrossDialectKnowledge
        store = ExperienceStore.__new__(ExperienceStore)
        store._storage_dir = "/tmp"
        store._lock = __import__("threading").Lock()

        kb = CrossDialectKnowledge(store, promotion_threshold=2)
        kb.record_pattern("postgresql", "fp1", "quote_ids",
                          "Always quote mixed-case identifiers")
        kb.record_pattern("postgresql", "fp2", "quote_ids",
                          "Always quote mixed-case identifiers")

        patterns = kb.get_patterns("postgresql")
        assert len(patterns) == 1
        assert patterns[0]["key"] == "quote_ids"
        assert patterns[0]["source_count"] == 2

    def test_no_duplicate_promotion(self):
        from mcpdb.experience.cross_dialect import CrossDialectKnowledge
        store = ExperienceStore.__new__(ExperienceStore)
        store._storage_dir = "/tmp"
        store._lock = __import__("threading").Lock()

        kb = CrossDialectKnowledge(store, promotion_threshold=2)
        kb.record_pattern("postgresql", "fp1", "p1", "Desc")
        kb.record_pattern("postgresql", "fp2", "p1", "Desc")
        kb.record_pattern("postgresql", "fp3", "p1", "Desc")  # third time

        assert len(kb.get_patterns("postgresql")) == 1

    def test_different_dialects_separate(self):
        from mcpdb.experience.cross_dialect import CrossDialectKnowledge
        store = ExperienceStore.__new__(ExperienceStore)
        store._storage_dir = "/tmp"
        store._lock = __import__("threading").Lock()

        kb = CrossDialectKnowledge(store, promotion_threshold=2)
        kb.record_pattern("postgresql", "fp1", "p1", "PG pattern")
        kb.record_pattern("mysql", "fp2", "p1", "MySQL pattern")

        assert kb.get_patterns("postgresql") == []
        assert kb.get_patterns("mysql") == []

    def test_pattern_context(self):
        from mcpdb.experience.cross_dialect import CrossDialectKnowledge
        store = ExperienceStore.__new__(ExperienceStore)
        store._storage_dir = "/tmp"
        store._lock = __import__("threading").Lock()

        kb = CrossDialectKnowledge(store, promotion_threshold=2)
        kb.record_pattern("postgresql", "fp1", "p1", "Quote identifiers")
        kb.record_pattern("postgresql", "fp2", "p1", "Quote identifiers")

        ctx = kb.get_pattern_context("postgresql")
        assert ctx is not None
        assert "Quote identifiers" in ctx

    def test_no_pattern_context(self):
        from mcpdb.experience.cross_dialect import CrossDialectKnowledge
        store = ExperienceStore.__new__(ExperienceStore)
        store._storage_dir = "/tmp"
        store._lock = __import__("threading").Lock()

        kb = CrossDialectKnowledge(store, promotion_threshold=2)
        assert kb.get_pattern_context("oracle") is None

    def test_get_all_dialects(self):
        from mcpdb.experience.cross_dialect import CrossDialectKnowledge
        store = ExperienceStore.__new__(ExperienceStore)
        store._storage_dir = "/tmp"
        store._lock = __import__("threading").Lock()

        kb = CrossDialectKnowledge(store, promotion_threshold=2)
        kb.record_pattern("pg", "fp1", "p1", "D")
        kb.record_pattern("pg", "fp2", "p1", "D")
        kb.record_pattern("mysql", "fp3", "p2", "D")
        kb.record_pattern("mysql", "fp4", "p2", "D")

        dialects = kb.get_all_dialects()
        assert "pg" in dialects
        assert "mysql" in dialects

    def test_stats(self):
        from mcpdb.experience.cross_dialect import CrossDialectKnowledge
        store = ExperienceStore.__new__(ExperienceStore)
        store._storage_dir = "/tmp"
        store._lock = __import__("threading").Lock()

        kb = CrossDialectKnowledge(store, promotion_threshold=2)
        kb.record_pattern("pg", "fp1", "p1", "D")
        kb.record_pattern("pg", "fp2", "p1", "D")

        stats = kb.get_stats()
        assert stats["dialects"] == 1
        assert stats["total_patterns"] == 1


# ---------------------------------------------------------------------------
# Schema drift detection
# ---------------------------------------------------------------------------

class TestSchemaDrift:
    def test_no_drift_same_schema(self):
        from mcpdb.experience.schema_drift import SchemaDriftDetector
        store = ExperienceStore.__new__(ExperienceStore)
        store._storage_dir = "/tmp"
        store._lock = __import__("threading").Lock()

        detector = SchemaDriftDetector(store)
        meta = _make_meta()
        detector.register_schema(meta)

        result = detector.check_drift(meta)
        assert not result.drifted
        assert not result.is_new

    def test_first_registration(self):
        from mcpdb.experience.schema_drift import SchemaDriftDetector
        store = ExperienceStore.__new__(ExperienceStore)
        store._storage_dir = "/tmp"
        store._lock = __import__("threading").Lock()

        detector = SchemaDriftDetector(store)
        meta = _make_meta()
        result = detector.check_drift(meta)
        assert not result.drifted
        assert result.is_new

    def test_drift_detected(self):
        from mcpdb.experience.schema_drift import SchemaDriftDetector
        store = ExperienceStore.__new__(ExperienceStore)
        store._storage_dir = "/tmp"
        store._lock = __import__("threading").Lock()

        detector = SchemaDriftDetector(store)
        meta_v1 = _make_meta()
        detector.register_schema(meta_v1)

        # Add a column → different schema
        meta_v2 = _make_meta(tables=[
            TableInfo(
                name="users",
                columns=[
                    ColumnInfo(name="id", dtype="int"),
                    ColumnInfo(name="name", dtype="str"),
                    ColumnInfo(name="email", dtype="str"),
                ],
            ),
        ])
        result = detector.check_drift(meta_v2)
        assert result.drifted
        assert result.previous_hash != ""
        assert result.current_hash != ""

    def test_drift_result_bool(self):
        from mcpdb.experience.schema_drift import DriftResult
        assert not DriftResult(drifted=False)
        assert DriftResult(drifted=True)

    def test_drift_result_repr(self):
        from mcpdb.experience.schema_drift import DriftResult
        r1 = DriftResult(drifted=False, is_new=True)
        assert "new_source" in repr(r1)

        r2 = DriftResult(drifted=True, previous_hash="abc", current_hash="def")
        assert "drifted" in repr(r2)

        r3 = DriftResult(drifted=False)
        assert "no_drift" in repr(r3)

    def test_handle_drift_clears_cache(self, tmp_path):
        from mcpdb.experience.schema_drift import SchemaDriftDetector
        from mcpdb.experience.records import SuccessRecord, CodeStep
        store = ExperienceStore(storage_dir=str(tmp_path))
        detector = SchemaDriftDetector(store)

        meta = _make_meta()
        fp = fingerprint_source(meta)
        sh = fingerprint_schema(meta)

        # Store a record with old schema
        record = SuccessRecord(
            intent_hash="ih1",
            question="test",
            source_fingerprint=fp,
            schema_hash="old_hash",  # different from current
            query_mode="simple",
            steps=[],
            response="answer",
        )
        store.store_success(record)

        count = detector.handle_drift(meta, invalidate_cache=True)
        assert count == 1

        # Store should be cleared
        assert store.get_successes(fp) == []

    def test_handle_drift_no_invalidate(self, tmp_path):
        from mcpdb.experience.schema_drift import SchemaDriftDetector
        store = ExperienceStore(storage_dir=str(tmp_path))
        detector = SchemaDriftDetector(store)
        meta = _make_meta()

        count = detector.handle_drift(meta, invalidate_cache=False)
        assert count == 0

    def test_get_known_schemas(self):
        from mcpdb.experience.schema_drift import SchemaDriftDetector
        store = ExperienceStore.__new__(ExperienceStore)
        store._storage_dir = "/tmp"
        store._lock = __import__("threading").Lock()

        detector = SchemaDriftDetector(store)
        meta = _make_meta()
        detector.register_schema(meta)

        schemas = detector.get_known_schemas()
        assert len(schemas) == 1


# ---------------------------------------------------------------------------
# Experience MCP tools
# ---------------------------------------------------------------------------

class TestExperienceMCPTools:
    def test_get_tools(self):
        from mcpdb.mcp.tools.experience import get_experience_tools
        tools = get_experience_tools()
        assert len(tools) == 5
        names = [t.name for t in tools]
        assert "get_experience_stats" in names
        assert "list_cached_queries" in names
        assert "invalidate_cache_entry" in names
        assert "clear_experience" in names
        assert "vote_response" in names

    def test_handle_no_cache(self):
        from mcpdb.mcp.tools.experience import handle_experience_tool
        from mcpdb.sources.registry import SourceRegistry
        result = handle_experience_tool("get_experience_stats", {}, SourceRegistry(), None)
        assert "not enabled" in result[0].text.lower()

    def test_handle_unknown_tool(self):
        from mcpdb.mcp.tools.experience import handle_experience_tool
        from mcpdb.sources.registry import SourceRegistry
        result = handle_experience_tool("unknown", {}, SourceRegistry(), object())
        assert "unknown" in result[0].text.lower()

    def test_get_stats(self, tmp_path):
        from mcpdb.mcp.tools.experience import handle_experience_tool
        from mcpdb.sources.registry import SourceRegistry
        from mcpdb.experience.cache import ExperienceCache

        store = ExperienceStore(storage_dir=str(tmp_path))
        cache = ExperienceCache(store)
        registry = SourceRegistry()

        result = handle_experience_tool(
            "get_experience_stats", {}, registry, cache
        )
        assert "memory cache" in result[0].text.lower()

    def test_vote_down_invalidates(self, tmp_path):
        from mcpdb.mcp.tools.experience import handle_experience_tool
        from mcpdb.sources.registry import SourceRegistry
        from mcpdb.experience.cache import ExperienceCache

        store = ExperienceStore(storage_dir=str(tmp_path))
        cache = ExperienceCache(store)
        registry = SourceRegistry()
        meta = _make_meta()
        registry.add_source(_MockSource(meta))

        result = handle_experience_tool(
            "vote_response",
            {"source_id": "test_src", "question": "test q", "vote": "down"},
            registry,
            cache,
        )
        assert "invalidated" in result[0].text.lower()

    def test_vote_up(self, tmp_path):
        from mcpdb.mcp.tools.experience import handle_experience_tool
        from mcpdb.sources.registry import SourceRegistry
        from mcpdb.experience.cache import ExperienceCache

        store = ExperienceStore(storage_dir=str(tmp_path))
        cache = ExperienceCache(store)
        registry = SourceRegistry()
        meta = _make_meta()
        registry.add_source(_MockSource(meta))

        result = handle_experience_tool(
            "vote_response",
            {"source_id": "test_src", "question": "test q", "vote": "up"},
            registry,
            cache,
        )
        assert "positive" in result[0].text.lower()
