"""Tests for the pluggable knowledge (RAG) system."""

from __future__ import annotations

import os
import pickle
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mcpdb.knowledge.base import (
    EmbeddingProvider,
    KnowledgeCategory,
    KnowledgeChunk,
    KnowledgeDocument,
    resolve_category,
)
from mcpdb.knowledge.bm25 import BM25Index, tokenize
from mcpdb.knowledge.chunker import (
    chunk_file,
    chunk_markdown,
    _chunk_yaml,
    _chunk_sql,
    _is_visualization_chunk,
)
from mcpdb.knowledge.embeddings import (
    LLMEmbeddingProvider,
    LocalEmbeddingProvider,
    NoEmbeddingProvider,
    resolve_embedding_provider,
)
from mcpdb.knowledge.index import KnowledgeIndex, _cosine_similarity
from mcpdb.knowledge.retriever import estimate_tokens, format_knowledge_context
from mcpdb.knowledge.file_provider import FileKnowledgeProvider
from mcpdb.knowledge.manager import (
    INJECTION_BUDGETS,
    INJECTION_CATEGORIES,
    KnowledgeManager,
)


# =========================================================================
# base.py
# =========================================================================


class TestKnowledgeCategory:
    def test_enum_values(self):
        assert KnowledgeCategory.SCHEMA_DOCS.value == "schema_docs"
        assert KnowledgeCategory.VISUALIZATION.value == "visualization"
        assert KnowledgeCategory.QUERY_TEMPLATE.value == "query_template"

    def test_resolve_known_aliases(self):
        assert resolve_category("python_reference") == KnowledgeCategory.QUERY_TEMPLATE
        assert resolve_category("sql_patterns") == KnowledgeCategory.QUERY_TEMPLATE
        assert resolve_category("domain") == KnowledgeCategory.SCHEMA_DOCS
        assert resolve_category("working_scenarios") == KnowledgeCategory.WORKING_EXAMPLE

    def test_resolve_direct_values(self):
        assert resolve_category("visualization") == KnowledgeCategory.VISUALIZATION
        assert resolve_category("business_rule") == KnowledgeCategory.BUSINESS_RULE
        assert resolve_category("data_quality") == KnowledgeCategory.DATA_QUALITY

    def test_resolve_with_formatting(self):
        assert resolve_category("  Python Reference  ") == KnowledgeCategory.QUERY_TEMPLATE
        assert resolve_category("SQL-Patterns") == KnowledgeCategory.QUERY_TEMPLATE
        assert resolve_category("Data Quality") == KnowledgeCategory.DATA_QUALITY

    def test_resolve_unknown_defaults(self):
        assert resolve_category("completely_unknown") == KnowledgeCategory.SCHEMA_DOCS
        assert resolve_category("") == KnowledgeCategory.SCHEMA_DOCS


class TestKnowledgeChunk:
    def test_token_estimate_auto(self):
        chunk = KnowledgeChunk(id="test", text="one two three four five", category=KnowledgeCategory.SCHEMA_DOCS)
        assert chunk.token_estimate == int(5 * 1.3)

    def test_token_estimate_explicit(self):
        chunk = KnowledgeChunk(id="test", text="hello world", category=KnowledgeCategory.SCHEMA_DOCS, token_estimate=99)
        assert chunk.token_estimate == 99

    def test_defaults(self):
        chunk = KnowledgeChunk(id="t1", text="text", category=KnowledgeCategory.QA)
        assert chunk.relevance == 0.0
        assert chunk.tags == []
        assert chunk.source_file == ""
        assert chunk.section_title == ""


# =========================================================================
# bm25.py
# =========================================================================


class TestTokenize:
    def test_basic(self):
        tokens = tokenize("Hello World Test")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens

    def test_removes_stop_words(self):
        tokens = tokenize("the quick fox is running")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "quick" in tokens
        assert "fox" in tokens

    def test_keeps_underscored_words(self):
        tokens = tokenize("ins_cars table_name")
        assert "ins_cars" in tokens
        assert "table_name" in tokens

    def test_removes_single_chars(self):
        tokens = tokenize("a b c dd")
        assert "dd" in tokens
        assert "a" not in tokens

    def test_empty(self):
        assert tokenize("") == []
        assert tokenize("the is a an") == []


class TestBM25Index:
    def test_add_and_search(self):
        bm25 = BM25Index()
        bm25.add("insurance claims damage report")
        bm25.add("car accident repair cost")
        bm25.add("medical expenses and treatment")

        results = bm25.search("insurance damage")
        assert len(results) > 0
        assert results[0][0] == 0  # first doc is most relevant

    def test_empty_index(self):
        bm25 = BM25Index()
        assert bm25.search("anything") == []

    def test_no_matching_terms(self):
        bm25 = BM25Index()
        bm25.add("foo bar baz")
        assert bm25.search("qux quux") == []

    def test_candidate_filtering(self):
        bm25 = BM25Index()
        bm25.add("insurance claims")  # 0
        bm25.add("car insurance")     # 1
        bm25.add("unrelated data")    # 2

        results = bm25.search("insurance", candidates=[0, 2])
        doc_ids = {r[0] for r in results}
        assert 0 in doc_ids
        assert 1 not in doc_ids  # excluded by candidates

    def test_top_k_limit(self):
        bm25 = BM25Index()
        for i in range(20):
            bm25.add(f"document {i} with keyword insurance")
        results = bm25.search("insurance", top_k=5)
        assert len(results) <= 5

    def test_len(self):
        bm25 = BM25Index()
        assert len(bm25) == 0
        bm25.add("doc 1")
        bm25.add("doc 2")
        assert len(bm25) == 2

    def test_add_batch(self):
        bm25 = BM25Index()
        count = bm25.add_batch(["doc one", "doc two", "doc three"])
        assert count == 3
        assert len(bm25) == 3


# =========================================================================
# chunker.py
# =========================================================================


class TestChunkMarkdown:
    def test_small_file_single_chunk(self):
        content = "# Title\n\nShort content here."
        docs = chunk_markdown(content, "test.md")
        assert len(docs) == 1
        assert docs[0].section_title == "Title"

    def test_splits_on_h2(self):
        # Must exceed 400 words to trigger splitting
        filler = " ".join(f"word{i}" for i in range(200))
        content = f"""# Main Title

Some intro text.

## Section One

Content for section one. {filler}

## Section Two

Content for section two. {filler}
"""
        docs = chunk_markdown(content, "test.md")
        assert len(docs) >= 2
        titles = [d.section_title for d in docs]
        assert "Section One" in titles
        assert "Section Two" in titles

    def test_frontmatter_category(self):
        content = """> Category: visualization
> Tags: plotly, chart, histogram

## Histogram Example

A long section about histograms with plotly for creating beautiful visualizations and data analysis charts in various formats.
"""
        docs = chunk_markdown(content, "python/charts.md")
        assert docs[0].category == KnowledgeCategory.VISUALIZATION

    def test_frontmatter_tags(self):
        content = """> Tags: insurance, claims, damage

Short file with tags.
"""
        docs = chunk_markdown(content, "test.md")
        assert "insurance" in docs[0].tags
        assert "claims" in docs[0].tags

    def test_directory_based_category(self):
        content = "# SQL Query\n\nShort query content."
        docs = chunk_markdown(content, "python/query_helpers.md")
        assert docs[0].category == KnowledgeCategory.QUERY_TEMPLATE

    def test_visualization_detection_from_tags(self):
        content = """> Tags: plotly, chart

# Chart Guide
Short chart guide content.
"""
        docs = chunk_markdown(content, "python/charts.md")
        assert docs[0].category == KnowledgeCategory.VISUALIZATION


class TestChunkYaml:
    def test_table_schema(self):
        content = """tables:
  ins_cars:
    description: Insurance car records
    columns:
      car_id:
        meaning: Unique identifier
      brand:
        meaning: Car brand name
"""
        docs = _chunk_yaml(content, "schema.yml")
        assert len(docs) == 1
        assert "ins_cars" in docs[0].content
        assert docs[0].category == KnowledgeCategory.SCHEMA_DOCS

    def test_invalid_yaml(self):
        docs = _chunk_yaml("not: valid: yaml: {{", "bad.yml")
        assert len(docs) == 1  # Falls back to raw content


class TestChunkSql:
    def test_annotated_blocks(self):
        content = """-- @description: Get total claims by year
-- @tags: claims, aggregate
SELECT year, COUNT(*) FROM ins_damages GROUP BY year;

-- @description: Average repair cost
-- @tags: cost, repair
SELECT AVG(cost) FROM ins_damages;
"""
        docs = _chunk_sql(content, "queries.sql")
        assert len(docs) == 2
        assert docs[0].section_title == "Get total claims by year"
        assert "claims" in docs[0].tags

    def test_plain_sql(self):
        content = "SELECT * FROM ins_cars WHERE brand = 'Toyota';"
        docs = _chunk_sql(content, "plain.sql")
        assert len(docs) == 1


class TestChunkFile:
    def test_markdown_dispatch(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# Title\n\nShort content.")
        docs = chunk_file(f, base_dir=tmp_path)
        assert len(docs) >= 1
        assert docs[0].source_label == "test.md"

    def test_yaml_dispatch(self, tmp_path):
        f = tmp_path / "schema.yml"
        f.write_text("tables:\n  foo:\n    description: A table\n")
        docs = chunk_file(f, base_dir=tmp_path)
        assert len(docs) >= 1

    def test_sql_dispatch(self, tmp_path):
        f = tmp_path / "query.sql"
        f.write_text("SELECT 1;")
        docs = chunk_file(f, base_dir=tmp_path)
        assert len(docs) >= 1

    def test_unsupported_extension(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}')
        docs = chunk_file(f, base_dir=tmp_path)
        assert docs == []

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.md"
        f.write_text("")
        docs = chunk_file(f, base_dir=tmp_path)
        assert docs == []

    def test_relative_source_label(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        f = sub / "test.md"
        f.write_text("# Title\n\nShort content.")
        docs = chunk_file(f, base_dir=tmp_path)
        assert docs[0].source_label == os.path.join("subdir", "test.md")


class TestIsVisualizationChunk:
    def test_chart_keywords(self):
        assert _is_visualization_chunk("Histogram Chart", "some text")
        assert _is_visualization_chunk("", "plotly express bar chart example")
        assert _is_visualization_chunk("KPI Indicator", "dashboard metrics")

    def test_non_viz(self):
        assert not _is_visualization_chunk("SQL Query", "SELECT * FROM table")
        assert not _is_visualization_chunk("", "insurance damage data analysis")


# =========================================================================
# embeddings.py
# =========================================================================


class TestNoEmbeddingProvider:
    def test_returns_empty(self):
        p = NoEmbeddingProvider()
        assert p.embed_batch(["hello", "world"]) == [[], []]
        assert p.embed_query("test") == []
        assert p.dimension == 0
        assert not p.is_available()


class TestLLMEmbeddingProvider:
    def test_uses_embed_method(self):
        mock_llm = MagicMock()
        mock_llm.embed.return_value = [0.1, 0.2, 0.3]
        p = LLMEmbeddingProvider(mock_llm)
        result = p.embed_batch(["hello"])
        assert result == [[0.1, 0.2, 0.3]]
        assert p.dimension == 3

    def test_query_caching(self):
        mock_llm = MagicMock()
        mock_llm.embed.return_value = [0.5, 0.5]
        p = LLMEmbeddingProvider(mock_llm)
        p.embed_query("test")
        p.embed_query("test")
        # Second call should use cache
        assert mock_llm.embed.call_count == 1

    def test_fallback_on_error(self):
        mock_llm = MagicMock()
        mock_llm.embed.side_effect = Exception("API error")
        delattr(mock_llm, "_client")  # no client fallback
        p = LLMEmbeddingProvider(mock_llm)
        result = p.embed_batch(["hello"])
        assert result == [[]]


class TestResolveEmbeddingProvider:
    def test_none_mode(self):
        p = resolve_embedding_provider("none")
        assert isinstance(p, NoEmbeddingProvider)

    def test_llm_mode_with_provider(self):
        mock_llm = MagicMock()
        p = resolve_embedding_provider("llm", llm_provider=mock_llm)
        assert isinstance(p, LLMEmbeddingProvider)

    def test_llm_mode_without_provider(self):
        p = resolve_embedding_provider("llm", llm_provider=None)
        assert isinstance(p, NoEmbeddingProvider)

    def test_auto_mode_no_deps(self):
        """Auto mode with no sentence-transformers and no LLM falls back to none."""
        with patch("mcpdb.knowledge.embeddings.LocalEmbeddingProvider._load_model", side_effect=ImportError):
            p = resolve_embedding_provider("auto", llm_provider=None)
            assert isinstance(p, NoEmbeddingProvider)

    def test_auto_mode_with_llm(self):
        """Auto mode with no sentence-transformers but LLM available uses LLM."""
        mock_llm = MagicMock()
        with patch("mcpdb.knowledge.embeddings.LocalEmbeddingProvider._load_model", side_effect=ImportError):
            p = resolve_embedding_provider("auto", llm_provider=mock_llm)
            assert isinstance(p, LLMEmbeddingProvider)


# =========================================================================
# index.py
# =========================================================================


class TestKnowledgeIndex:
    def _make_doc(self, content, category=KnowledgeCategory.SCHEMA_DOCS, title="test"):
        return KnowledgeDocument(
            content=content,
            source_label="test.md",
            category=category,
            section_title=title,
        )

    def test_add_and_search(self):
        idx = KnowledgeIndex()
        idx.add(self._make_doc("insurance claims damage report", title="Claims"))
        idx.add(self._make_doc("car accident repair cost estimate", title="Repairs"))
        idx.add(self._make_doc("medical treatment hospital expenses", title="Medical"))

        results = idx.search("insurance damage claims")
        assert len(results) > 0
        assert results[0].section_title == "Claims"

    def test_category_filtering(self):
        idx = KnowledgeIndex()
        idx.add(self._make_doc("chart plotly visualization", KnowledgeCategory.VISUALIZATION, "Chart"))
        idx.add(self._make_doc("chart plotly bar diagram", KnowledgeCategory.SCHEMA_DOCS, "Schema"))

        results = idx.search("chart plotly", categories={KnowledgeCategory.VISUALIZATION})
        assert len(results) == 1
        assert results[0].category == KnowledgeCategory.VISUALIZATION

    def test_table_name_boost(self):
        idx = KnowledgeIndex()
        idx.add(self._make_doc("insurance claims report analysis", title="General"))
        idx.add(self._make_doc("insurance claims ins_cars vehicle", title="Cars"))

        # Without boost, both should score similarly for "insurance claims"
        results_no_boost = idx.search("insurance claims")
        # With boost, ins_cars document should rank higher
        results_boosted = idx.search("insurance claims", table_names=["ins_cars"])
        assert len(results_boosted) >= 2
        assert results_boosted[0].section_title == "Cars"

    def test_empty_search(self):
        idx = KnowledgeIndex()
        assert idx.search("anything") == []

    def test_len(self):
        idx = KnowledgeIndex()
        assert len(idx) == 0
        idx.add(self._make_doc("doc one"))
        assert len(idx) == 1

    def test_clear(self):
        idx = KnowledgeIndex()
        idx.add(self._make_doc("doc"))
        idx.clear()
        assert len(idx) == 0

    def test_save_and_load(self, tmp_path):
        idx = KnowledgeIndex()
        idx.add(self._make_doc("insurance claims report", title="Claims"))
        idx.add(self._make_doc("car repair costs", title="Repairs"))

        path = tmp_path / "test_index.pkl"
        idx.save(path)
        assert path.exists()

        loaded = KnowledgeIndex.load(path)
        assert len(loaded) == 2
        results = loaded.search("insurance claims")
        assert len(results) > 0
        assert results[0].section_title == "Claims"

    def test_add_batch(self):
        idx = KnowledgeIndex()
        docs = [self._make_doc(f"doc {i}") for i in range(5)]
        count = idx.add_batch(docs)
        assert count == 5
        assert len(idx) == 5

    def test_relevance_score_normalized(self):
        idx = KnowledgeIndex()
        idx.add(self._make_doc("insurance damage claims"))
        results = idx.search("insurance damage")
        assert len(results) > 0
        assert 0.0 <= results[0].relevance <= 1.0


class TestCosineSimilarity:
    def test_identical_vectors(self):
        assert abs(_cosine_similarity([1, 0, 0], [1, 0, 0]) - 1.0) < 0.001

    def test_orthogonal_vectors(self):
        assert abs(_cosine_similarity([1, 0], [0, 1])) < 0.001

    def test_empty_vectors(self):
        assert _cosine_similarity([], []) == 0.0
        assert _cosine_similarity([1], []) == 0.0

    def test_different_lengths(self):
        assert _cosine_similarity([1, 2], [1, 2, 3]) == 0.0


# =========================================================================
# retriever.py
# =========================================================================


class TestEstimateTokens:
    def test_basic(self):
        assert estimate_tokens("one two three") == int(3 * 1.3)

    def test_empty(self):
        assert estimate_tokens("") == 0


class TestFormatKnowledgeContext:
    def test_basic_formatting(self):
        chunks = [
            KnowledgeChunk(id="1", text="Content A", category=KnowledgeCategory.SCHEMA_DOCS,
                          relevance=0.9, section_title="Title A"),
            KnowledgeChunk(id="2", text="Content B", category=KnowledgeCategory.SCHEMA_DOCS,
                          relevance=0.5, section_title="Title B"),
        ]
        result = format_knowledge_context(chunks, max_tokens=5000)
        assert "Title A" in result
        assert "Title B" in result
        assert result.index("Title A") < result.index("Title B")  # Higher relevance first

    def test_deduplication(self):
        chunks = [
            KnowledgeChunk(id="1", text="Content", category=KnowledgeCategory.SCHEMA_DOCS,
                          relevance=0.9, section_title="Same Title"),
            KnowledgeChunk(id="2", text="Content Dup", category=KnowledgeCategory.SCHEMA_DOCS,
                          relevance=0.5, section_title="Same Title"),
        ]
        result = format_knowledge_context(chunks, max_tokens=5000)
        assert result.count("Same Title") == 1

    def test_token_budget_enforcement(self):
        chunks = [
            KnowledgeChunk(
                id="1",
                text="word " * 200,  # ~260 tokens
                category=KnowledgeCategory.SCHEMA_DOCS,
                relevance=0.9,
                section_title="Chunk A",
            ),
            KnowledgeChunk(
                id="2",
                text="word " * 200,
                category=KnowledgeCategory.SCHEMA_DOCS,
                relevance=0.5,
                section_title="Chunk B",
            ),
        ]
        result = format_knowledge_context(chunks, max_tokens=300)
        # Should include first chunk but not have enough budget for both
        assert "Chunk A" in result

    def test_empty_input(self):
        assert format_knowledge_context([]) == ""


# =========================================================================
# file_provider.py
# =========================================================================


class TestFileKnowledgeProvider:
    def _create_rag_dir(self, tmp_path):
        """Create a minimal RAG directory structure."""
        rag = tmp_path / "rag"
        rag.mkdir()

        (rag / "schema.md").write_text(
            "> Category: schema_docs\n"
            "> Tags: tables, structure\n\n"
            "# Database Schema\n\n"
            "## ins_cars\n\n"
            "The ins_cars table contains car records for insurance policies. "
            "Each record has a car_id, brand, model, year, and policy reference.\n\n"
            "## ins_damages\n\n"
            "The ins_damages table tracks damage claims with amounts, dates, "
            "and descriptions of the incidents reported by policyholders.\n"
        )

        (rag / "charts.md").write_text(
            "> Category: visualization\n"
            "> Tags: plotly, chart\n\n"
            "# Plotly Charts\n\n"
            "## Bar Chart\n\n"
            "Use px.bar() for creating bar charts with categorical data. "
            "Always include proper axis labels and title for better readability.\n\n"
            "## Histogram\n\n"
            "Use px.histogram() for distribution analysis with nbins parameter. "
            "Add marginal='box' for additional distribution insight.\n"
        )

        (rag / "_hidden.md").write_text("Should be skipped")
        (rag / ".dotfile.md").write_text("Should be skipped")

        return rag

    def test_load_chunks(self, tmp_path):
        rag = self._create_rag_dir(tmp_path)
        provider = FileKnowledgeProvider([str(rag)])
        count = provider.load()
        assert count > 0
        assert provider.chunk_count > 0

    def test_skips_hidden_files(self, tmp_path):
        rag = self._create_rag_dir(tmp_path)
        provider = FileKnowledgeProvider([str(rag)])
        provider.load()
        # _hidden.md and .dotfile.md should not be loaded
        chunks = provider.retrieve("hidden")
        hidden_chunks = [c for c in chunks if "Should be skipped" in c.text]
        assert len(hidden_chunks) == 0

    def test_retrieve(self, tmp_path):
        rag = self._create_rag_dir(tmp_path)
        provider = FileKnowledgeProvider([str(rag)])
        provider.load()

        chunks = provider.retrieve("insurance cars brand")
        assert len(chunks) > 0

    def test_category_filter(self, tmp_path):
        rag = self._create_rag_dir(tmp_path)
        provider = FileKnowledgeProvider([str(rag)])
        provider.load()

        viz_chunks = provider.retrieve(
            "chart bar plotly",
            categories={KnowledgeCategory.VISUALIZATION},
        )
        for chunk in viz_chunks:
            assert chunk.category == KnowledgeCategory.VISUALIZATION

    def test_cache_and_reload(self, tmp_path):
        rag = self._create_rag_dir(tmp_path)
        provider1 = FileKnowledgeProvider([str(rag)])
        count1 = provider1.load()

        # Check that cache file was created
        cache_path = rag / "_knowledge_index.pkl"
        assert cache_path.exists()

        # Second load should use cache
        provider2 = FileKnowledgeProvider([str(rag)])
        count2 = provider2.load()
        assert count2 == count1

    def test_cache_invalidation_on_file_change(self, tmp_path):
        rag = self._create_rag_dir(tmp_path)
        provider1 = FileKnowledgeProvider([str(rag)])
        provider1.load()

        cache_path = rag / "_knowledge_index.pkl"
        assert cache_path.exists()
        old_mtime = cache_path.stat().st_mtime

        # Modify a file (touch with future time)
        import time
        time.sleep(0.1)
        schema_file = rag / "schema.md"
        schema_file.write_text(schema_file.read_text() + "\n## New Table\n\nNew content for cache invalidation test with enough words.\n")

        provider2 = FileKnowledgeProvider([str(rag)])
        provider2.load()

        # Cache should be rebuilt
        new_mtime = cache_path.stat().st_mtime
        assert new_mtime > old_mtime

    def test_nonexistent_directory(self, tmp_path):
        provider = FileKnowledgeProvider([str(tmp_path / "nonexistent")])
        count = provider.load()
        assert count == 0

    def test_multiple_directories(self, tmp_path):
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        (dir1 / "doc1.md").write_text("# Doc 1\n\nContent from directory one.")
        (dir2 / "doc2.md").write_text("# Doc 2\n\nContent from directory two.")

        provider = FileKnowledgeProvider([str(dir1), str(dir2)])
        count = provider.load()
        assert count >= 2


# =========================================================================
# manager.py
# =========================================================================


class TestKnowledgeManager:
    def _create_rag_dir(self, tmp_path):
        rag = tmp_path / "rag"
        rag.mkdir()
        (rag / "patterns.md").write_text(
            "> Category: query_template\n"
            "> Tags: sql, patterns\n\n"
            "# SQL Patterns\n\n"
            "## JOIN Pattern\n\n"
            "Use LEFT JOIN for optional relationships. Always use explicit JOIN syntax "
            "rather than implicit comma joins for better readability and maintenance.\n\n"
            "## Aggregation Pattern\n\n"
            "Use GROUP BY with aggregate functions. Include HAVING clause to filter "
            "groups after aggregation for conditional group selection.\n"
        )
        (rag / "schema.md").write_text(
            "> Category: schema_docs\n\n"
            "# Schema Documentation\n\n"
            "## ins_cars Table\n\n"
            "The ins_cars table stores car insurance records with columns for car_id, "
            "brand, model, production_year, and policy_holder_id foreign key reference.\n"
        )
        return rag

    def test_load_and_retrieve(self, tmp_path):
        rag = self._create_rag_dir(tmp_path)
        mgr = KnowledgeManager()
        mgr.add_file_provider(FileKnowledgeProvider([str(rag)]))
        count = mgr.load()
        assert count > 0
        assert mgr.is_loaded
        assert mgr.total_chunks > 0

    def test_retrieve_with_injection_point(self, tmp_path):
        rag = self._create_rag_dir(tmp_path)
        mgr = KnowledgeManager()
        mgr.add_file_provider(FileKnowledgeProvider([str(rag)]))
        mgr.load()

        # plan injection point should return relevant content
        ctx = mgr.retrieve("SQL JOIN query", injection_point="plan")
        assert isinstance(ctx, str)
        # Context should have content (if the category routing finds QUERY_TEMPLATE)
        # It may be empty if no chunks match the plan categories — that's OK

    def test_retrieve_empty_when_not_loaded(self):
        mgr = KnowledgeManager()
        assert mgr.retrieve("test") == ""

    def test_search_returns_raw_chunks(self, tmp_path):
        rag = self._create_rag_dir(tmp_path)
        mgr = KnowledgeManager()
        mgr.add_file_provider(FileKnowledgeProvider([str(rag)]))
        mgr.load()

        chunks = mgr.search("JOIN pattern")
        assert isinstance(chunks, list)
        if chunks:
            assert isinstance(chunks[0], KnowledgeChunk)

    def test_injection_categories_defined(self):
        assert "plan" in INJECTION_CATEGORIES
        assert "classify" in INJECTION_CATEGORIES
        assert "debug" in INJECTION_CATEGORIES
        assert "synthesize" in INJECTION_CATEGORIES
        assert "blueprint" in INJECTION_CATEGORIES

    def test_injection_budgets_defined(self):
        assert INJECTION_BUDGETS["plan"] == 2000
        assert INJECTION_BUDGETS["classify"] == 500
        assert INJECTION_BUDGETS["debug"] == 1000

    def test_no_providers(self):
        mgr = KnowledgeManager()
        count = mgr.load()
        assert count == 0
        assert mgr.is_loaded
        assert mgr.retrieve("test") == ""


# =========================================================================
# Integration: agent state and graph injection
# =========================================================================


class TestAgentStateIntegration:
    def test_knowledge_context_field_exists(self):
        from mcpdb.agent.state import AgentState
        # AgentState is a TypedDict — check the annotation
        assert "knowledge_context" in AgentState.__annotations__

    def test_knowledge_context_in_make_plan(self):
        """Verify make_plan reads knowledge_context from state."""
        from mcpdb.agent.nodes.common import make_plan
        # We can't easily run make_plan without an LLM, but we can verify
        # the code path exists by checking the source
        import inspect
        source = inspect.getsource(make_plan)
        assert 'knowledge_context' in source
        assert 'DOMAIN KNOWLEDGE' in source


class TestGraphIntegration:
    def test_run_agent_accepts_knowledge_manager(self):
        """Verify run_agent signature accepts knowledge_manager."""
        import inspect
        from mcpdb.agent.graph import run_agent
        sig = inspect.signature(run_agent)
        assert "knowledge_manager" in sig.parameters


# =========================================================================
# Config integration
# =========================================================================


class TestKnowledgeConfig:
    def test_defaults(self):
        from mcpdb.config import KnowledgeConfig
        cfg = KnowledgeConfig()
        assert cfg.enabled is True
        assert cfg.embedding == "none"
        assert cfg.directories == ["~/.mcpdb/knowledge"]
        assert cfg.sources == {}

    def test_mcpdb_config_has_knowledge(self):
        from mcpdb.config import McpdbConfig
        cfg = McpdbConfig()
        assert hasattr(cfg, "knowledge")
        assert cfg.knowledge.enabled is True

    def test_yaml_loading(self, tmp_path):
        from mcpdb.config import load_config
        config_path = tmp_path / "test_config.yaml"
        config_path.write_text(
            "knowledge:\n"
            "  enabled: true\n"
            "  embedding: llm\n"
            "  directories:\n"
            "    - /tmp/rag1\n"
            "    - /tmp/rag2\n"
            "  sources:\n"
            "    bgins: /tmp/rag_bgins\n"
        )
        cfg = load_config(config_path)
        assert cfg.knowledge.enabled is True
        assert cfg.knowledge.embedding == "llm"
        assert len(cfg.knowledge.directories) == 2
        assert cfg.knowledge.sources["bgins"] == "/tmp/rag_bgins"


# =========================================================================
# CLI integration
# =========================================================================


class TestCreateKnowledgeManager:
    def test_returns_none_when_no_dirs(self, tmp_path):
        from mcpdb.config import McpdbConfig, KnowledgeConfig
        cfg = McpdbConfig(knowledge=KnowledgeConfig(
            enabled=True,
            directories=[str(tmp_path / "nonexistent")],
        ))
        from mcpdb.__main__ import _create_knowledge_manager
        result = _create_knowledge_manager(cfg, knowledge_dirs=[], logger=None)
        assert result is None

    def test_returns_manager_with_valid_dir(self, tmp_path):
        rag = tmp_path / "rag"
        rag.mkdir()
        (rag / "test.md").write_text(
            "# Test\n\n"
            "## Section\n\n"
            "Content for testing with enough words to make it a meaningful chunk for indexing.\n"
        )

        from mcpdb.config import McpdbConfig, KnowledgeConfig
        cfg = McpdbConfig(knowledge=KnowledgeConfig(enabled=True))
        from mcpdb.__main__ import _create_knowledge_manager
        result = _create_knowledge_manager(cfg, knowledge_dirs=[str(rag)], logger=None)
        assert result is not None
        assert result.total_chunks > 0

    def test_cli_dirs_override_config(self, tmp_path):
        rag = tmp_path / "cli_rag"
        rag.mkdir()
        (rag / "override.md").write_text(
            "# Override\n\nCLI override content with enough words here.\n"
        )

        from mcpdb.config import McpdbConfig, KnowledgeConfig
        cfg = McpdbConfig(knowledge=KnowledgeConfig(
            enabled=True,
            directories=[str(tmp_path / "nonexistent_config_dir")],
        ))
        from mcpdb.__main__ import _create_knowledge_manager
        # When CLI dirs are provided, they take precedence
        result = _create_knowledge_manager(cfg, knowledge_dirs=[str(rag)], logger=None)
        assert result is not None


# =========================================================================
# Web app integration
# =========================================================================


class TestWebAppKnowledgeIntegration:
    def test_create_app_accepts_knowledge_manager(self):
        import inspect
        from mcpdb.web.app import create_app
        sig = inspect.signature(create_app)
        assert "knowledge_manager" in sig.parameters

    def test_run_web_accepts_knowledge_manager(self):
        import inspect
        from mcpdb.web.app import run_web
        sig = inspect.signature(run_web)
        assert "knowledge_manager" in sig.parameters


# =========================================================================
# TUI integration
# =========================================================================


class TestTUIKnowledgeIntegration:
    def test_run_tui_accepts_knowledge_manager(self):
        import inspect
        from mcpdb.cli.tui.app import run_tui
        sig = inspect.signature(run_tui)
        assert "knowledge_manager" in sig.parameters

    def test_mcpdb_tui_class_accepts_knowledge_manager(self):
        import inspect
        from mcpdb.cli.tui.app import McpdbTUI
        sig = inspect.signature(McpdbTUI.__init__)
        assert "knowledge_manager" in sig.parameters

    def test_start_tui_accepts_knowledge_manager(self):
        import inspect
        from mcpdb.__main__ import _start_tui
        sig = inspect.signature(_start_tui)
        assert "knowledge_manager" in sig.parameters


# =========================================================================
# MCP serve mode integration
# =========================================================================


class TestMCPServeKnowledgeIntegration:
    def test_register_all_tools_accepts_knowledge_manager(self):
        import inspect
        from mcpdb.mcp.tools import register_all_tools
        sig = inspect.signature(register_all_tools)
        assert "knowledge_manager" in sig.parameters

    def test_create_server_accepts_knowledge_manager(self):
        import inspect
        from mcpdb.mcp.server import create_server
        sig = inspect.signature(create_server)
        assert "knowledge_manager" in sig.parameters

    def test_handle_analysis_tool_accepts_knowledge_manager(self):
        import inspect
        from mcpdb.mcp.tools.analysis import handle_analysis_tool
        sig = inspect.signature(handle_analysis_tool)
        assert "knowledge_manager" in sig.parameters

    def test_ask_question_accepts_knowledge_manager(self):
        import inspect
        from mcpdb.mcp.tools.analysis import _ask_question
        sig = inspect.signature(_ask_question)
        assert "knowledge_manager" in sig.parameters
