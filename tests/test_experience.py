"""Tests for v2.3.x — Experience System (Basic).

Covers fingerprinting, JSONL store, exact-match cache,
schema drift detection, and agent integration.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from mcpdb.experience.fingerprint import (
    fingerprint_source,
    fingerprint_schema,
    intent_hash,
)
from mcpdb.experience.records import CodeStep, FailureRecord, SuccessRecord
from mcpdb.experience.store import ExperienceStore
from mcpdb.experience.cache import ExperienceCache
from mcpdb.sources.base import ColumnInfo, SourceMetadata, SourceType, TableInfo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def source_metadata() -> SourceMetadata:
    return SourceMetadata(
        source_id="test_db_1",
        source_type=SourceType.DATABASE,
        display_name="Test DB",
        tables=[
            TableInfo(
                name="customers",
                columns=[
                    ColumnInfo(name="id", dtype="int"),
                    ColumnInfo(name="name", dtype="text"),
                    ColumnInfo(name="email", dtype="text"),
                ],
                row_count=100,
            ),
            TableInfo(
                name="orders",
                columns=[
                    ColumnInfo(name="id", dtype="int"),
                    ColumnInfo(name="customer_id", dtype="int"),
                    ColumnInfo(name="total", dtype="float"),
                ],
                row_count=500,
            ),
        ],
        capabilities={"sql"},
    )


@pytest.fixture
def altered_metadata() -> SourceMetadata:
    """Same tables but different column set (schema drift)."""
    return SourceMetadata(
        source_id="test_db_1",
        source_type=SourceType.DATABASE,
        display_name="Test DB",
        tables=[
            TableInfo(
                name="customers",
                columns=[
                    ColumnInfo(name="id", dtype="int"),
                    ColumnInfo(name="name", dtype="text"),
                    ColumnInfo(name="email", dtype="text"),
                    ColumnInfo(name="phone", dtype="text"),  # New column
                ],
                row_count=100,
            ),
            TableInfo(
                name="orders",
                columns=[
                    ColumnInfo(name="id", dtype="int"),
                    ColumnInfo(name="customer_id", dtype="int"),
                    ColumnInfo(name="total", dtype="float"),
                ],
                row_count=500,
            ),
        ],
        capabilities={"sql"},
    )


@pytest.fixture
def store(tmp_path) -> ExperienceStore:
    return ExperienceStore(storage_dir=str(tmp_path / "experience"))


@pytest.fixture
def cache(store) -> ExperienceCache:
    return ExperienceCache(store=store)


# ---------------------------------------------------------------------------
# Fingerprint tests
# ---------------------------------------------------------------------------

class TestFingerprint:
    def test_deterministic(self, source_metadata):
        fp1 = fingerprint_source(source_metadata)
        fp2 = fingerprint_source(source_metadata)
        assert fp1 == fp2

    def test_different_sources_different_fp(self, source_metadata):
        other = SourceMetadata(
            source_id="other",
            source_type=SourceType.CSV,
            display_name="Other",
            tables=[
                TableInfo(name="data", columns=[ColumnInfo(name="x", dtype="int")]),
            ],
            capabilities={"sql"},
        )
        fp1 = fingerprint_source(source_metadata)
        fp2 = fingerprint_source(other)
        assert fp1 != fp2

    def test_same_schema_same_fp(self, source_metadata):
        """Same tables/columns but different source_id → same fingerprint."""
        clone = SourceMetadata(
            source_id="different_id",
            source_type=source_metadata.source_type,
            display_name="Different Name",
            tables=source_metadata.tables,
            capabilities=source_metadata.capabilities,
        )
        assert fingerprint_source(source_metadata) == fingerprint_source(clone)

    def test_fingerprint_length(self, source_metadata):
        fp = fingerprint_source(source_metadata)
        assert len(fp) == 16

    def test_schema_hash(self, source_metadata):
        sh = fingerprint_schema(source_metadata)
        assert len(sh) == 12

    def test_schema_hash_changes_on_drift(self, source_metadata, altered_metadata):
        sh1 = fingerprint_schema(source_metadata)
        sh2 = fingerprint_schema(altered_metadata)
        assert sh1 != sh2

    def test_intent_hash_deterministic(self, source_metadata):
        fp = fingerprint_source(source_metadata)
        h1 = intent_hash("Show top customers", fp)
        h2 = intent_hash("Show top customers", fp)
        assert h1 == h2

    def test_intent_hash_case_insensitive(self, source_metadata):
        fp = fingerprint_source(source_metadata)
        h1 = intent_hash("Show Top Customers", fp)
        h2 = intent_hash("show top customers", fp)
        assert h1 == h2

    def test_intent_hash_strips_whitespace(self, source_metadata):
        fp = fingerprint_source(source_metadata)
        h1 = intent_hash("  Show top customers  ", fp)
        h2 = intent_hash("Show top customers", fp)
        assert h1 == h2

    def test_different_questions_different_hash(self, source_metadata):
        fp = fingerprint_source(source_metadata)
        h1 = intent_hash("Show top customers", fp)
        h2 = intent_hash("Show top orders", fp)
        assert h1 != h2


# ---------------------------------------------------------------------------
# Records tests
# ---------------------------------------------------------------------------

class TestRecords:
    def test_success_record_round_trip(self):
        record = SuccessRecord(
            intent_hash="abc123",
            question="Show top 10 customers",
            source_fingerprint="fp123",
            schema_hash="sh123",
            query_mode="simple",
            steps=[
                CodeStep(
                    action_type="sql",
                    code="SELECT * FROM customers LIMIT 10",
                    result_preview="10 rows",
                    time_ms=42.5,
                ),
            ],
            response="Here are the top 10 customers...",
        )

        d = record.to_dict()
        restored = SuccessRecord.from_dict(d)

        assert restored.intent_hash == record.intent_hash
        assert restored.question == record.question
        assert restored.query_mode == record.query_mode
        assert len(restored.steps) == 1
        assert restored.steps[0].code == "SELECT * FROM customers LIMIT 10"
        assert restored.response == record.response

    def test_failure_record_round_trip(self):
        record = FailureRecord(
            question="Bad query",
            source_fingerprint="fp123",
            error_type="SQLError",
            error_message="table not found",
            failed_code="SELECT * FROM nonexistent",
        )

        d = record.to_dict()
        restored = FailureRecord.from_dict(d)

        assert restored.question == record.question
        assert restored.error_type == record.error_type
        assert restored.error_message == record.error_message

    def test_code_step_defaults(self):
        step = CodeStep(action_type="sql", code="SELECT 1")
        assert step.result_preview == ""
        assert step.time_ms == 0.0


# ---------------------------------------------------------------------------
# ExperienceStore tests
# ---------------------------------------------------------------------------

class TestExperienceStore:
    def test_store_and_retrieve_success(self, store):
        record = SuccessRecord(
            intent_hash="test_hash",
            question="test question",
            source_fingerprint="fp_abc",
            schema_hash="sh_abc",
            query_mode="simple",
            steps=[],
            response="Test response",
        )
        store.store_success(record)

        results = store.get_successes("fp_abc")
        assert len(results) == 1
        assert results[0].intent_hash == "test_hash"
        assert results[0].response == "Test response"

    def test_store_and_retrieve_failure(self, store):
        record = FailureRecord(
            question="bad query",
            source_fingerprint="fp_abc",
            error_type="SQLError",
            error_message="syntax error",
        )
        store.store_failure(record)

        results = store.get_failures("fp_abc")
        assert len(results) == 1
        assert results[0].error_type == "SQLError"

    def test_find_by_intent(self, store):
        record = SuccessRecord(
            intent_hash="unique_hash",
            question="test",
            source_fingerprint="fp_xyz",
            schema_hash="sh_xyz",
            query_mode="quick",
            steps=[],
            response="Found it!",
        )
        store.store_success(record)

        found = store.find_by_intent("fp_xyz", "unique_hash")
        assert found is not None
        assert found.response == "Found it!"

        not_found = store.find_by_intent("fp_xyz", "nonexistent")
        assert not_found is None

    def test_different_fingerprints_isolated(self, store):
        r1 = SuccessRecord(
            intent_hash="h1", question="q1", source_fingerprint="fp_a",
            schema_hash="sh_a", query_mode="simple", steps=[], response="r1",
        )
        r2 = SuccessRecord(
            intent_hash="h2", question="q2", source_fingerprint="fp_b",
            schema_hash="sh_b", query_mode="simple", steps=[], response="r2",
        )
        store.store_success(r1)
        store.store_success(r2)

        assert len(store.get_successes("fp_a")) == 1
        assert len(store.get_successes("fp_b")) == 1
        assert len(store.get_successes("fp_c")) == 0

    def test_compact(self, store):
        # Create a store with low limits
        small_store = ExperienceStore(
            storage_dir=str(store._storage_dir),
            max_success=2,
            max_failure=1,
        )

        # Add 5 success records
        for i in range(5):
            small_store.store_success(SuccessRecord(
                intent_hash=f"h{i}", question=f"q{i}", source_fingerprint="fp_test",
                schema_hash="sh", query_mode="simple", steps=[], response=f"r{i}",
                timestamp=time.time() + i,
            ))

        removed = small_store.compact("fp_test")
        assert removed == 3  # 5 - 2 = 3

        remaining = small_store.get_successes("fp_test")
        assert len(remaining) == 2

    def test_clear(self, store):
        store.store_success(SuccessRecord(
            intent_hash="h", question="q", source_fingerprint="fp_clear",
            schema_hash="sh", query_mode="simple", steps=[], response="r",
        ))
        assert len(store.get_successes("fp_clear")) == 1

        store.clear("fp_clear")
        assert len(store.get_successes("fp_clear")) == 0

    def test_list_fingerprints(self, store):
        store.store_success(SuccessRecord(
            intent_hash="h1", question="q1", source_fingerprint="fp_one",
            schema_hash="sh", query_mode="simple", steps=[], response="r1",
        ))
        store.store_success(SuccessRecord(
            intent_hash="h2", question="q2", source_fingerprint="fp_two",
            schema_hash="sh", query_mode="simple", steps=[], response="r2",
        ))

        fps = store.list_fingerprints()
        assert "fp_one" in fps
        assert "fp_two" in fps

    def test_get_stats(self, store):
        store.store_success(SuccessRecord(
            intent_hash="h", question="q", source_fingerprint="fp_stats",
            schema_hash="sh", query_mode="simple", steps=[], response="r",
        ))
        store.store_failure(FailureRecord(
            question="q", source_fingerprint="fp_stats",
            error_type="E", error_message="m",
        ))

        stats = store.get_stats("fp_stats")
        assert stats["successes"] == 1
        assert stats["failures"] == 1
        assert stats["total_records"] == 2

    def test_corrupt_record_skipped(self, store):
        """Corrupt lines in JSONL should be skipped."""
        fp = "fp_corrupt"
        path = store._source_path(fp)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write("not valid json\n")
            f.write(json.dumps(SuccessRecord(
                intent_hash="h", question="q", source_fingerprint=fp,
                schema_hash="sh", query_mode="simple", steps=[], response="r",
            ).to_dict()) + "\n")

        results = store.get_successes(fp)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# ExperienceCache tests
# ---------------------------------------------------------------------------

class TestExperienceCache:
    def test_store_and_lookup(self, cache, source_metadata):
        cache.store(
            question="Show top customers",
            source_metadata=source_metadata,
            query_mode="simple",
            steps=[CodeStep(action_type="sql", code="SELECT * FROM customers")],
            response="Here are the top customers.",
        )

        result = cache.lookup("Show top customers", source_metadata)
        assert result is not None
        assert result.response == "Here are the top customers."

    def test_cache_miss(self, cache, source_metadata):
        result = cache.lookup("Unknown question", source_metadata)
        assert result is None

    def test_case_insensitive_match(self, cache, source_metadata):
        cache.store(
            question="Show top customers",
            source_metadata=source_metadata,
            query_mode="simple",
            steps=[],
            response="Response",
        )

        result = cache.lookup("show top customers", source_metadata)
        assert result is not None

    def test_schema_drift_invalidation(self, cache, source_metadata, altered_metadata):
        cache.store(
            question="Show top customers",
            source_metadata=source_metadata,
            query_mode="simple",
            steps=[],
            response="Old response",
        )

        # Same question but schema has changed
        result = cache.lookup("Show top customers", altered_metadata)
        assert result is None

    def test_age_expiry(self, store, source_metadata):
        """Records older than max_age_days should be invalid."""
        cache = ExperienceCache(store=store, max_age_days=0)  # Immediate expiry

        cache.store(
            question="Show top customers",
            source_metadata=source_metadata,
            query_mode="simple",
            steps=[],
            response="Response",
        )

        # Force timestamp to be old
        fp = cache._store.list_fingerprints()[0]
        records = cache._store._load_records(fp)
        records[0]["timestamp"] = time.time() - 86400 * 2

        # Rewrite with old timestamp
        path = cache._store._source_path(fp)
        with open(path, "w") as f:
            f.write(json.dumps(records[0]) + "\n")

        # Clear memory cache to force disk lookup
        cache._memory.clear()

        result = cache.lookup("Show top customers", source_metadata)
        assert result is None

    def test_invalidate(self, cache, source_metadata):
        cache.store(
            question="Show top customers",
            source_metadata=source_metadata,
            query_mode="simple",
            steps=[],
            response="Response",
        )

        cache.invalidate("Show top customers", source_metadata)

        # Memory cache cleared, but disk record still exists
        # (invalidate only clears memory)
        assert cache.lookup("Show top customers", source_metadata) is not None

    def test_clear_source(self, cache, source_metadata):
        cache.store(
            question="Q1",
            source_metadata=source_metadata,
            query_mode="simple",
            steps=[],
            response="R1",
        )
        cache.store(
            question="Q2",
            source_metadata=source_metadata,
            query_mode="simple",
            steps=[],
            response="R2",
        )

        cache.clear_source(source_metadata)

        assert cache.lookup("Q1", source_metadata) is None
        assert cache.lookup("Q2", source_metadata) is None

    def test_get_stats(self, cache, source_metadata):
        cache.store(
            question="Q1",
            source_metadata=source_metadata,
            query_mode="simple",
            steps=[],
            response="R1",
        )

        stats = cache.get_stats()
        assert stats["memory_entries"] >= 1
        assert stats["disk_sources"] >= 1
        assert stats["disk_total_successes"] >= 1

    def test_memory_eviction(self, store, source_metadata):
        cache = ExperienceCache(store=store, max_age_days=30)
        cache._max_memory = 3

        for i in range(5):
            cache.store(
                question=f"Question {i}",
                source_metadata=source_metadata,
                query_mode="simple",
                steps=[],
                response=f"Response {i}",
            )

        assert len(cache._memory) <= 3


# ---------------------------------------------------------------------------
# Agent integration tests
# ---------------------------------------------------------------------------

class TestAgentIntegration:
    @pytest.fixture
    def mock_registry(self, source_metadata):
        """Create a mock registry that returns our source metadata."""
        from unittest.mock import MagicMock
        registry = MagicMock()
        registry.list_sources.return_value = [source_metadata]
        registry.get_combined_context.return_value = "Test context"
        return registry

    @pytest.fixture
    def mock_llm(self):
        from unittest.mock import AsyncMock, MagicMock
        llm = MagicMock()
        llm.generate = AsyncMock(return_value=("mocked response", {"input_tokens": 10, "output_tokens": 5}))
        llm.generate_json = AsyncMock(return_value=(
            {"query_mode": "quick", "target_sources": [], "requires_cross_source": False, "key_entities": []},
            {"input_tokens": 10, "output_tokens": 5},
        ))
        return llm

    @pytest.mark.asyncio
    async def test_cache_hit_skips_agent(
        self, cache, source_metadata, mock_registry, mock_llm
    ):
        from mcpdb.agent.graph import run_agent
        from mcpdb.agent.callbacks import CallbackManager

        # Pre-populate cache
        cache.store(
            question="What tables exist?",
            source_metadata=source_metadata,
            query_mode="quick",
            steps=[],
            response="There are 2 tables: customers and orders.",
        )

        callbacks = CallbackManager()
        state = await run_agent(
            question="What tables exist?",
            registry=mock_registry,
            llm=mock_llm,
            callbacks=callbacks,
            experience_cache=cache,
        )

        assert state.get("cache_hit") is True
        assert state.get("response") == "There are 2 tables: customers and orders."

        # Check that a cache_hit event was emitted
        events = callbacks.get_events()
        event_types = [e.type for e in events]
        assert "experience/cache_hit" in event_types

    @pytest.mark.asyncio
    async def test_cache_miss_runs_normally(
        self, cache, source_metadata, mock_registry, mock_llm
    ):
        from mcpdb.agent.graph import run_agent
        from mcpdb.agent.callbacks import CallbackManager

        callbacks = CallbackManager()
        state = await run_agent(
            question="What tables exist?",
            registry=mock_registry,
            llm=mock_llm,
            callbacks=callbacks,
            experience_cache=cache,
        )

        assert state.get("cache_hit") is not True or state.get("cache_hit") is False

    @pytest.mark.asyncio
    async def test_no_cache_works_normally(self, mock_registry, mock_llm):
        """Agent runs fine without experience cache."""
        from mcpdb.agent.graph import run_agent
        from mcpdb.agent.callbacks import CallbackManager

        state = await run_agent(
            question="What tables exist?",
            registry=mock_registry,
            llm=mock_llm,
            callbacks=CallbackManager(),
            experience_cache=None,
        )

        # Should have run normally (no error)
        assert state.get("query_mode") is not None
