"""Tests for v2.4.x — Experience Templates (Semantic).

Covers embeddings/similarity, template retrieval, anti-pattern tracking,
and planning integration.
"""

from __future__ import annotations

import time

import pytest

from mcpdb.experience.embeddings import (
    cosine_similarity,
    jaccard_similarity,
    weighted_similarity,
    _tokenize,
)
from mcpdb.experience.retriever import TemplateRetriever, RetrievalResult
from mcpdb.experience.antipatterns import (
    AntiPatternTracker,
    _simplify_error,
    _generate_hint,
)
from mcpdb.experience.records import CodeStep, FailureRecord, SuccessRecord
from mcpdb.experience.store import ExperienceStore
from mcpdb.experience.fingerprint import fingerprint_source
from mcpdb.sources.base import ColumnInfo, SourceMetadata, SourceType, TableInfo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def source_metadata() -> SourceMetadata:
    return SourceMetadata(
        source_id="test_db",
        source_type=SourceType.DATABASE,
        display_name="Test DB",
        tables=[
            TableInfo(
                name="customers",
                columns=[
                    ColumnInfo(name="id", dtype="int"),
                    ColumnInfo(name="name", dtype="text"),
                    ColumnInfo(name="revenue", dtype="float"),
                ],
                row_count=1000,
            ),
            TableInfo(
                name="orders",
                columns=[
                    ColumnInfo(name="id", dtype="int"),
                    ColumnInfo(name="customer_id", dtype="int"),
                    ColumnInfo(name="amount", dtype="float"),
                ],
                row_count=5000,
            ),
        ],
        capabilities={"sql"},
    )


@pytest.fixture
def store(tmp_path) -> ExperienceStore:
    return ExperienceStore(storage_dir=str(tmp_path / "experience"))


@pytest.fixture
def retriever(store) -> TemplateRetriever:
    return TemplateRetriever(
        store=store,
        threshold_high=0.75,  # Lowered for testing with short texts
        threshold_medium=0.50,
    )


@pytest.fixture
def tracker(store) -> AntiPatternTracker:
    return AntiPatternTracker(store=store, min_occurrences=2)


# ---------------------------------------------------------------------------
# Tokenize tests
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_basic(self):
        tokens = _tokenize("Show top 10 customers by revenue")
        assert "top" in tokens
        assert "10" in tokens
        assert "customers" in tokens
        assert "revenue" in tokens

    def test_stop_words_removed(self):
        tokens = _tokenize("What is the total of all orders")
        assert "total" in tokens
        assert "orders" in tokens
        assert "what" not in tokens
        assert "the" not in tokens
        assert "is" not in tokens

    def test_case_insensitive(self):
        tokens = _tokenize("SELECT Customers FROM Database")
        assert "select" in tokens
        assert "customers" in tokens
        assert "database" in tokens

    def test_empty_string(self):
        assert _tokenize("") == set()


# ---------------------------------------------------------------------------
# Jaccard similarity tests
# ---------------------------------------------------------------------------

class TestJaccardSimilarity:
    def test_identical(self):
        sim = jaccard_similarity(
            "Show top 10 customers by revenue",
            "Show top 10 customers by revenue",
        )
        assert sim == 1.0

    def test_similar(self):
        sim = jaccard_similarity(
            "Show top 10 customers by revenue",
            "Show top 5 customers by revenue",
        )
        assert sim > 0.5

    def test_different(self):
        sim = jaccard_similarity(
            "Show top customers by revenue",
            "Delete all database tables permanently",
        )
        assert sim < 0.2

    def test_empty(self):
        assert jaccard_similarity("", "") == 0.0
        assert jaccard_similarity("hello", "") == 0.0

    def test_symmetric(self):
        a = "Show top customers by revenue"
        b = "Display customer revenue ranking"
        assert jaccard_similarity(a, b) == jaccard_similarity(b, a)


class TestWeightedSimilarity:
    def test_table_overlap_boost(self):
        base = jaccard_similarity(
            "customers revenue analysis",
            "customers spending analysis",
        )
        boosted = weighted_similarity(
            "customers revenue analysis",
            "customers spending analysis",
            table_names_a={"customers"},
            table_names_b={"customers"},
        )
        assert boosted >= base

    def test_no_table_overlap(self):
        base = jaccard_similarity("query A", "query B")
        no_boost = weighted_similarity(
            "query A", "query B",
            table_names_a={"orders"},
            table_names_b={"customers"},
        )
        # No overlap means no boost
        assert no_boost == base

    def test_no_tables_provided(self):
        base = jaccard_similarity("query A", "query B")
        result = weighted_similarity("query A", "query B")
        assert result == base


class TestCosineSimilarity:
    def test_identical(self):
        assert cosine_similarity([1, 0, 0], [1, 0, 0]) == 1.0

    def test_orthogonal(self):
        assert cosine_similarity([1, 0], [0, 1]) == 0.0

    def test_opposite(self):
        assert cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)

    def test_zero_vector(self):
        assert cosine_similarity([0, 0], [1, 1]) == 0.0


# ---------------------------------------------------------------------------
# Template retriever tests
# ---------------------------------------------------------------------------

class TestTemplateRetriever:
    def _store_record(self, store, fingerprint, question, mode="simple"):
        store.store_success(SuccessRecord(
            intent_hash=f"h_{question[:10]}",
            question=question,
            source_fingerprint=fingerprint,
            schema_hash="sh123",
            query_mode=mode,
            steps=[
                CodeStep(action_type="sql", code="SELECT * FROM customers LIMIT 10"),
            ],
            response=f"Answer to: {question}",
        ))

    def test_retrieve_similar(self, retriever, store, source_metadata):
        fp = fingerprint_source(source_metadata)
        self._store_record(store, fp, "Show top 10 customers by revenue")

        results = retriever.retrieve(
            "Show top 10 customers by revenue",
            source_metadata,
        )
        assert len(results) >= 1
        assert results[0].similarity > 0.5

    def test_retrieve_no_match(self, retriever, store, source_metadata):
        fp = fingerprint_source(source_metadata)
        self._store_record(store, fp, "completely unrelated xyzzy plugh")

        results = retriever.retrieve(
            "Show top customers by revenue",
            source_metadata,
        )
        # Low similarity should be filtered out
        for r in results:
            assert r.similarity >= 0.5

    def test_retrieve_empty_store(self, retriever, source_metadata):
        results = retriever.retrieve("Any question", source_metadata)
        assert results == []

    def test_retrieve_max_results(self, retriever, store, source_metadata):
        fp = fingerprint_source(source_metadata)
        for i in range(10):
            self._store_record(store, fp, f"Show top {i} customers by revenue")

        results = retriever.retrieve(
            "Show top customers by revenue",
            source_metadata,
            max_results=3,
        )
        assert len(results) <= 3

    def test_template_context_high_match(self, retriever, store, source_metadata):
        fp = fingerprint_source(source_metadata)
        self._store_record(store, fp, "Show top 10 customers by revenue")

        context = retriever.get_template_context(
            "Show top 10 customers by revenue",
            source_metadata,
        )
        assert context is not None
        assert "Similar Successful Approach" in context or "Related Past Query" in context

    def test_template_context_no_match(self, retriever, source_metadata):
        context = retriever.get_template_context(
            "Completely unrelated query xyz abc",
            source_metadata,
        )
        assert context is None

    def test_extract_table_references(self, retriever, source_metadata):
        refs = retriever._extract_table_references(
            "Show all customers and their orders",
            source_metadata,
        )
        assert "customers" in refs
        assert "orders" in refs

    def test_match_type_classification(self, retriever, store, source_metadata):
        fp = fingerprint_source(source_metadata)
        self._store_record(store, fp, "Show top 10 customers by revenue ranking now")

        results = retriever.retrieve(
            "Show top 10 customers by revenue ranking now",
            source_metadata,
        )
        if results:
            assert results[0].match_type in ("template", "hint")


# ---------------------------------------------------------------------------
# Anti-pattern tracker tests
# ---------------------------------------------------------------------------

class TestAntiPatternTracker:
    def test_single_failure_not_promoted(self, tracker, source_metadata):
        tracker.record_failure(
            question="bad query",
            source_metadata=source_metadata,
            error_type="SQLError",
            error_message="column 'foo' not found",
        )

        patterns = tracker.get_anti_patterns(source_metadata)
        assert len(patterns) == 0

    def test_repeated_failure_promoted(self, tracker, source_metadata):
        for _ in range(3):
            tracker.record_failure(
                question="bad query",
                source_metadata=source_metadata,
                error_type="SQLError",
                error_message="column 'foo' not found",
            )

        patterns = tracker.get_anti_patterns(source_metadata)
        assert len(patterns) >= 1
        assert patterns[0]["error_type"] == "SQLError"
        assert patterns[0]["occurrences"] >= 2

    def test_different_errors_separate(self, tracker, source_metadata):
        tracker.record_failure(
            question="q1", source_metadata=source_metadata,
            error_type="SQLError", error_message="syntax error",
        )
        tracker.record_failure(
            question="q2", source_metadata=source_metadata,
            error_type="TimeoutError", error_message="query timed out",
        )

        patterns = tracker.get_anti_patterns(source_metadata)
        # Neither has 2 occurrences
        assert len(patterns) == 0

    def test_anti_pattern_context(self, tracker, source_metadata):
        for _ in range(2):
            tracker.record_failure(
                question="q", source_metadata=source_metadata,
                error_type="SQLError", error_message="column 'revenue' not found",
                failed_code="SELECT revenue FROM products",
            )

        context = tracker.get_anti_pattern_context(source_metadata)
        assert context is not None
        assert "Anti-Patterns" in context
        assert "SQLError" in context

    def test_anti_pattern_context_none(self, tracker, source_metadata):
        context = tracker.get_anti_pattern_context(source_metadata)
        assert context is None

    def test_avoidance_hints(self, tracker, source_metadata):
        for _ in range(2):
            tracker.record_failure(
                question="q", source_metadata=source_metadata,
                error_type="SQLError", error_message="column 'x' not found",
            )

        patterns = tracker.get_anti_patterns(source_metadata)
        assert patterns[0]["avoidance_hint"] != ""


class TestSimplifyError:
    def test_removes_quotes(self):
        result = _simplify_error("column 'revenue' not found in table 'sales'")
        assert "'...'" in result
        assert "revenue" not in result

    def test_removes_numbers(self):
        result = _simplify_error("row 42 out of range 100")
        assert "N" in result

    def test_truncates(self):
        long_msg = "x" * 200
        result = _simplify_error(long_msg)
        assert len(result) <= 100


class TestGenerateHint:
    def test_column_not_found(self):
        r = FailureRecord(
            question="q", source_fingerprint="fp",
            error_type="E", error_message="column 'x' not found",
        )
        assert "column" in _generate_hint(r).lower()

    def test_table_not_found(self):
        r = FailureRecord(
            question="q", source_fingerprint="fp",
            error_type="E", error_message="table 'orders' not found",
        )
        assert "table" in _generate_hint(r).lower()

    def test_syntax_error(self):
        r = FailureRecord(
            question="q", source_fingerprint="fp",
            error_type="E", error_message="SQL syntax error near SELECT",
        )
        assert "syntax" in _generate_hint(r).lower()

    def test_timeout(self):
        r = FailureRecord(
            question="q", source_fingerprint="fp",
            error_type="E", error_message="query timeout after 30s",
        )
        hint = _generate_hint(r)
        assert "LIMIT" in hint or "sampling" in hint

    def test_generic(self):
        r = FailureRecord(
            question="q", source_fingerprint="fp",
            error_type="E", error_message="unknown weird error",
        )
        hint = _generate_hint(r)
        assert len(hint) > 0


# ---------------------------------------------------------------------------
# Planning integration tests
# ---------------------------------------------------------------------------

class TestPlanningIntegration:
    @pytest.mark.asyncio
    async def test_make_plan_with_experience_context(self):
        """make_plan accepts experience_context parameter."""
        from unittest.mock import AsyncMock, MagicMock
        from mcpdb.agent.nodes.common import make_plan
        from mcpdb.agent.callbacks import CallbackManager

        llm = MagicMock()
        llm.generate_json = AsyncMock(return_value=(
            {
                "analysis": "test",
                "approach": "test",
                "steps": [{"step_number": 1, "action": "sql", "code": "SELECT 1"}],
            },
            {"input_tokens": 10, "output_tokens": 5},
        ))

        registry = MagicMock()
        callbacks = CallbackManager()

        state = {
            "question": "Show top customers",
            "source_context": "Test context",
        }

        experience_context = (
            "## Similar Successful Approach\n"
            "Question: Show top 10 customers\n"
            "Steps: SELECT * FROM customers ORDER BY revenue DESC LIMIT 10"
        )

        result = await make_plan(
            state, llm, callbacks, registry,
            experience_context=experience_context,
        )

        assert result.get("plan") is not None
        assert len(result["plan"]["steps"]) == 1

        # Verify the experience context was included in the prompt
        call_args = llm.generate_json.call_args
        prompt_text = call_args[0][0][0].content
        assert "Similar Successful Approach" in prompt_text

    @pytest.mark.asyncio
    async def test_make_plan_without_experience(self):
        """make_plan works without experience_context (backward compat)."""
        from unittest.mock import AsyncMock, MagicMock
        from mcpdb.agent.nodes.common import make_plan
        from mcpdb.agent.callbacks import CallbackManager

        llm = MagicMock()
        llm.generate_json = AsyncMock(return_value=(
            {
                "analysis": "test",
                "approach": "test",
                "steps": [],
            },
            {"input_tokens": 10, "output_tokens": 5},
        ))

        state = {
            "question": "test",
            "source_context": "test",
        }

        result = await make_plan(
            state, llm, CallbackManager(), MagicMock(),
        )
        assert result.get("plan") is not None
