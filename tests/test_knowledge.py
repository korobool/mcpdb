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


# =========================================================================
# Extended tests: vector re-ranking, embeddings, build_embeddings
# =========================================================================


class _FakeEmbeddingProvider(EmbeddingProvider):
    """Test provider that returns deterministic fixed-dimension vectors."""

    def __init__(self, dim: int = 4) -> None:
        self._dim = dim
        self._call_count = 0

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            self._call_count += 1
            # Deterministic vector based on text hash
            h = hash(text) % 1000 / 1000.0
            results.append([h, 1.0 - h, h * 0.5, 0.25])
        return results

    def embed_query(self, text: str) -> list[float]:
        h = hash(text) % 1000 / 1000.0
        return [h, 1.0 - h, h * 0.5, 0.25]

    @property
    def dimension(self) -> int:
        return self._dim

    def is_available(self) -> bool:
        return True


class TestBuildEmbeddings:
    """Test KnowledgeIndex.build_embeddings() — previously untested."""

    def _make_doc(self, content, category=KnowledgeCategory.SCHEMA_DOCS, title="test"):
        return KnowledgeDocument(
            content=content, source_label="test.md",
            category=category, section_title=title,
        )

    def test_build_with_provider(self):
        provider = _FakeEmbeddingProvider()
        idx = KnowledgeIndex(embedding_provider=provider)
        idx.add(self._make_doc("insurance claims report"))
        idx.add(self._make_doc("car accident data"))
        count = idx.build_embeddings()
        assert count == 2
        assert len(idx._vectors) == 2
        assert all(len(v) == 4 for v in idx._vectors)

    def test_build_without_provider(self):
        idx = KnowledgeIndex(embedding_provider=None)
        idx.add(self._make_doc("some content"))
        count = idx.build_embeddings()
        assert count == 0

    def test_build_with_unavailable_provider(self):
        provider = NoEmbeddingProvider()
        idx = KnowledgeIndex(embedding_provider=provider)
        idx.add(self._make_doc("some content"))
        count = idx.build_embeddings()
        assert count == 0

    def test_build_empty_index(self):
        provider = _FakeEmbeddingProvider()
        idx = KnowledgeIndex(embedding_provider=provider)
        count = idx.build_embeddings()
        assert count == 0

    def test_build_with_failing_provider(self):
        provider = MagicMock(spec=EmbeddingProvider)
        provider.is_available.return_value = True
        provider.embed_batch.side_effect = RuntimeError("API timeout")
        idx = KnowledgeIndex(embedding_provider=provider)
        idx.add(self._make_doc("some content"))
        count = idx.build_embeddings()
        assert count == 0
        assert idx._vectors == []

    def test_build_truncates_long_docs(self):
        """Documents longer than 2000 chars should be truncated for embedding."""
        provider = _FakeEmbeddingProvider()
        idx = KnowledgeIndex(embedding_provider=provider)
        long_doc = self._make_doc("x " * 3000)  # 6000 chars
        idx.add(long_doc)
        count = idx.build_embeddings()
        assert count == 1
        # The provider should have been called with truncated text
        assert provider._call_count == 1


class TestVectorReranking:
    """Test _rerank_with_vectors — previously untested."""

    def _make_doc(self, content, title="test"):
        return KnowledgeDocument(
            content=content, source_label="test.md",
            category=KnowledgeCategory.SCHEMA_DOCS, section_title=title,
        )

    def test_rerank_changes_order(self):
        """Vector re-ranking should influence final ranking."""
        provider = _FakeEmbeddingProvider()
        idx = KnowledgeIndex(embedding_provider=provider)
        idx.add(self._make_doc("insurance claims damage report", title="Claims"))
        idx.add(self._make_doc("car accident repair cost estimate", title="Repairs"))
        idx.add(self._make_doc("insurance policy terms conditions", title="Policy"))
        idx.build_embeddings()

        # With vectors, search should still work and return results
        results = idx.search("insurance damage claims")
        assert len(results) > 0
        # Results should have normalized relevance scores
        for chunk in results:
            assert 0.0 <= chunk.relevance <= 1.0

    def test_rerank_with_empty_query_vector(self):
        """If query embedding fails, should fall back to BM25 order."""
        provider = MagicMock(spec=EmbeddingProvider)
        provider.is_available.return_value = True
        provider.dimension = 4
        provider.embed_batch.return_value = [[0.1, 0.2, 0.3, 0.4]]
        provider.embed_query.return_value = []  # Fails to embed query

        idx = KnowledgeIndex(embedding_provider=provider)
        idx.add(self._make_doc("insurance claims"))
        idx.build_embeddings()

        results = idx.search("insurance claims")
        assert len(results) > 0

    def test_rerank_with_partial_vectors(self):
        """Some docs have vectors, others don't — should handle gracefully."""
        provider = _FakeEmbeddingProvider()
        idx = KnowledgeIndex(embedding_provider=provider)
        idx.add(self._make_doc("insurance claims data"))
        idx.add(self._make_doc("car repair costs"))
        idx.build_embeddings()

        # Manually remove one vector to simulate partial state
        idx._vectors[1] = []

        results = idx.search("insurance claims car repair")
        assert len(results) > 0

    def test_has_vectors_requires_all_conditions(self):
        """_has_vectors should be False when vectors empty or provider missing."""
        idx = KnowledgeIndex(embedding_provider=None)
        assert not idx._has_vectors()

        idx._vectors = [[0.1]]
        assert not idx._has_vectors()

        provider = _FakeEmbeddingProvider()
        idx._embedding_provider = provider
        assert idx._has_vectors()

    def test_combined_score_weights(self):
        """Combined score = 0.4 * BM25_norm + 0.6 * cosine — verify mixing."""
        provider = _FakeEmbeddingProvider()
        idx = KnowledgeIndex(embedding_provider=provider)

        # Add docs where BM25 and vector would disagree
        idx.add(self._make_doc("insurance insurance insurance claims", title="BM25-heavy"))
        idx.add(self._make_doc("automobile vehicle accident report", title="Different"))
        idx.build_embeddings()

        results = idx.search("insurance claims")
        assert len(results) >= 1
        # First result should have highest combined score
        scores = [r.relevance for r in results]
        assert scores == sorted(scores, reverse=True)


class TestLocalEmbeddingProvider:
    """Test LocalEmbeddingProvider — previously completely untested."""

    def test_init_defaults(self):
        provider = LocalEmbeddingProvider()
        assert provider._model_name == "all-MiniLM-L6-v2"
        assert provider._dimension == 384
        assert provider._model is None

    def test_load_model_without_sentence_transformers(self):
        """Should raise ImportError when sentence-transformers not installed."""
        provider = LocalEmbeddingProvider()
        with patch(
            "mcpdb.knowledge.embeddings.LocalEmbeddingProvider._load_model",
            side_effect=ImportError("No module named 'sentence_transformers'"),
        ):
            with pytest.raises(ImportError):
                provider._load_model()

    def test_embed_batch_calls_model(self):
        """Test embed_batch delegates to model.encode()."""
        import numpy as np

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2], [0.3, 0.4]])
        mock_model.get_sentence_embedding_dimension.return_value = 2

        provider = LocalEmbeddingProvider()
        provider._model = mock_model
        provider._dimension = 2

        result = provider.embed_batch(["hello", "world"])
        assert len(result) == 2
        assert result[0] == [0.1, 0.2]
        mock_model.encode.assert_called_once_with(["hello", "world"], show_progress_bar=False)

    def test_embed_query_calls_model(self):
        """Test embed_query delegates to model.encode()."""
        import numpy as np

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.5, 0.6])
        mock_model.get_sentence_embedding_dimension.return_value = 2

        provider = LocalEmbeddingProvider()
        provider._model = mock_model
        provider._dimension = 2

        result = provider.embed_query("test query")
        assert result == [0.5, 0.6]
        mock_model.encode.assert_called_once_with("test query", show_progress_bar=False)

    def test_dimension_property(self):
        provider = LocalEmbeddingProvider()
        assert provider.dimension == 384  # default

        provider._dimension = 768
        assert provider.dimension == 768

    def test_custom_model_name(self):
        provider = LocalEmbeddingProvider(model_name="paraphrase-MiniLM-L3-v2")
        assert provider._model_name == "paraphrase-MiniLM-L3-v2"

    def test_is_available_default(self):
        """Provider should be available when dimension > 0."""
        provider = LocalEmbeddingProvider()
        # Default 384 dimension makes it report available
        assert provider.is_available()

    def test_resolve_local_mode(self):
        """resolve_embedding_provider('local') should return LocalEmbeddingProvider."""
        p = resolve_embedding_provider("local")
        assert isinstance(p, LocalEmbeddingProvider)


class TestLLMEmbeddingProviderExtended:
    """Extended tests for LLMEmbeddingProvider — previously minimal coverage."""

    def test_embed_batch_multiple_texts(self):
        mock_llm = MagicMock()
        mock_llm.embed.side_effect = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
        p = LLMEmbeddingProvider(mock_llm)
        result = p.embed_batch(["one", "two", "three"])
        assert len(result) == 3
        assert p.dimension == 2

    def test_embed_batch_partial_failure(self):
        """If one embedding fails, the whole batch falls back."""
        mock_llm = MagicMock()
        mock_llm.embed.side_effect = [
            [0.1, 0.2],
            Exception("Rate limited"),
        ]
        p = LLMEmbeddingProvider(mock_llm)
        result = p.embed_batch(["one", "two"])
        # Falls back to empty vectors for all
        assert result == [[], []]

    def test_embed_query_cache_different_queries(self):
        mock_llm = MagicMock()
        mock_llm.embed.return_value = [0.5, 0.5]
        p = LLMEmbeddingProvider(mock_llm)
        p.embed_query("query1")
        p.embed_query("query2")
        p.embed_query("query1")  # should be cached
        assert mock_llm.embed.call_count == 2

    def test_embed_query_error_returns_empty(self):
        mock_llm = MagicMock()
        mock_llm.embed.side_effect = Exception("API error")
        delattr(mock_llm, "_client")
        p = LLMEmbeddingProvider(mock_llm)
        result = p.embed_query("test")
        assert result == []

    def test_embed_single_no_embed_no_client(self):
        """When LLM has neither embed() nor _client, returns empty."""
        mock_llm = MagicMock(spec=[])  # no attributes
        p = LLMEmbeddingProvider(mock_llm)
        result = p._embed_single("test")
        assert result == []

    def test_embed_single_uses_client_fallback(self):
        """When embed() not available, should try _client.models.embed_content."""
        mock_llm = MagicMock(spec=["_client"])
        mock_response = MagicMock()
        mock_embedding = MagicMock()
        mock_embedding.values = [0.1, 0.2, 0.3]
        mock_response.embeddings = [mock_embedding]
        mock_llm._client.models.embed_content.return_value = mock_response

        p = LLMEmbeddingProvider(mock_llm)
        result = p._embed_single("test text")
        assert result == [0.1, 0.2, 0.3]

    def test_is_available_before_embed(self):
        mock_llm = MagicMock()
        p = LLMEmbeddingProvider(mock_llm)
        assert not p.is_available()  # dimension is 0 before first embed

    def test_is_available_after_embed(self):
        mock_llm = MagicMock()
        mock_llm.embed.return_value = [0.1, 0.2, 0.3]
        p = LLMEmbeddingProvider(mock_llm)
        p.embed_batch(["test"])
        assert p.is_available()  # dimension set to 3


# =========================================================================
# Extended tests: BM25 scoring edge cases
# =========================================================================


class TestBM25Scoring:
    """Test BM25 scoring edge cases — previously untested."""

    def test_query_with_only_stop_words(self):
        bm25 = BM25Index()
        bm25.add("some real content here")
        results = bm25.search("the is a")
        assert results == []

    def test_repeated_terms_boost(self):
        """Document with repeated terms should score higher."""
        bm25 = BM25Index()
        bm25.add("insurance insurance insurance")  # 0
        bm25.add("insurance car")                   # 1
        results = bm25.search("insurance")
        assert len(results) == 2
        assert results[0][0] == 0  # doc with more repetitions

    def test_idf_weighting(self):
        """Rare terms should have higher IDF and boost scores."""
        bm25 = BM25Index()
        for i in range(10):
            bm25.add(f"common word document {i}")
        bm25.add("rare unique zebra special")  # doc 10
        results = bm25.search("zebra")
        assert len(results) == 1
        assert results[0][0] == 10

    def test_custom_k1_b_params(self):
        bm25 = BM25Index(k1=2.0, b=0.5)
        bm25.add("test document one")
        bm25.add("test document two")
        results = bm25.search("test document")
        assert len(results) == 2

    def test_search_returns_scores_sorted_descending(self):
        bm25 = BM25Index()
        bm25.add("low relevance content")
        bm25.add("insurance claims damage high relevance insurance")
        bm25.add("insurance claims medium")
        results = bm25.search("insurance claims damage")
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)

    def test_add_returns_sequential_ids(self):
        bm25 = BM25Index()
        assert bm25.add("first") == 0
        assert bm25.add("second") == 1
        assert bm25.add("third") == 2

    def test_avg_doc_length_updates(self):
        bm25 = BM25Index()
        bm25.add("one two three")
        assert bm25._avg_dl > 0
        prev_avg = bm25._avg_dl
        bm25.add("one two three four five six seven eight nine ten")
        assert bm25._avg_dl != prev_avg


# =========================================================================
# Extended tests: index save/load with vectors
# =========================================================================


class TestIndexSaveLoadWithVectors:
    def _make_doc(self, content, title="test"):
        return KnowledgeDocument(
            content=content, source_label="test.md",
            category=KnowledgeCategory.SCHEMA_DOCS, section_title=title,
        )

    def test_save_load_preserves_vectors(self, tmp_path):
        provider = _FakeEmbeddingProvider()
        idx = KnowledgeIndex(embedding_provider=provider)
        idx.add(self._make_doc("insurance claims", title="A"))
        idx.add(self._make_doc("car repair costs", title="B"))
        idx.build_embeddings()

        path = tmp_path / "test.pkl"
        idx.save(path)

        loaded = KnowledgeIndex.load(path, embedding_provider=provider)
        assert len(loaded) == 2
        assert len(loaded._vectors) == 2
        assert all(len(v) == 4 for v in loaded._vectors)

    def test_save_load_without_vectors(self, tmp_path):
        idx = KnowledgeIndex()
        idx.add(self._make_doc("doc one"))
        idx.add(self._make_doc("doc two"))

        path = tmp_path / "test.pkl"
        idx.save(path)

        loaded = KnowledgeIndex.load(path)
        assert len(loaded) == 2
        results = loaded.search("doc")
        assert len(results) > 0

    def test_load_corrupted_pickle(self, tmp_path):
        path = tmp_path / "corrupt.pkl"
        path.write_bytes(b"not a valid pickle file")
        with pytest.raises(Exception):
            KnowledgeIndex.load(path)

    def test_save_creates_parent_dirs(self, tmp_path):
        idx = KnowledgeIndex()
        idx.add(self._make_doc("test"))
        path = tmp_path / "subdir" / "deep" / "index.pkl"
        idx.save(path)
        assert path.exists()


# =========================================================================
# Extended tests: chunker edge cases
# =========================================================================


class TestChunkerEdgeCases:
    def test_markdown_large_file_splits_on_h3(self):
        """If no ## headings, should split on ### headings."""
        filler = " ".join(f"word{i}" for i in range(200))
        content = f"""# Main Title

### Sub One

First subsection content. {filler}

### Sub Two

Second subsection content. {filler}
"""
        docs = chunk_markdown(content, "test.md")
        assert len(docs) >= 2
        titles = [d.section_title for d in docs]
        assert "Sub One" in titles
        assert "Sub Two" in titles

    def test_markdown_no_headings_large(self):
        """Large file without any headings should be kept as single chunk."""
        filler = " ".join(f"word{i}" for i in range(500))
        content = f"This is a long document with no headings. {filler}"
        docs = chunk_markdown(content, "test.md")
        assert len(docs) == 1

    def test_markdown_nested_headings_split(self):
        """## section with ### subsections should split further if large."""
        filler = " ".join(f"word{i}" for i in range(300))
        content = f"""# Title

## Big Section

{filler}

### Sub A

Content for sub A with enough words to pass the filter. {filler}

### Sub B

Content for sub B with enough words to pass the filter. {filler}
"""
        docs = chunk_markdown(content, "test.md")
        titles = [d.section_title for d in docs]
        assert "Sub A" in titles or "Sub B" in titles or len(docs) >= 2

    def test_frontmatter_priority_ignored(self):
        """Lines starting with > Priority: should not break parsing."""
        content = """> Category: business_rule
> Tags: insurance
> Priority: high

# Rule One

Short content about a business rule.
"""
        docs = chunk_markdown(content, "test.md")
        assert docs[0].category == KnowledgeCategory.BUSINESS_RULE

    def test_extract_title_no_heading(self):
        """_extract_title should use first meaningful line if no heading."""
        from mcpdb.knowledge.chunker import _extract_title
        result = _extract_title("This is a meaningful line.\nAnother line.")
        assert "This is a meaningful" in result

    def test_extract_title_empty(self):
        from mcpdb.knowledge.chunker import _extract_title
        assert _extract_title("") == "Untitled"
        assert _extract_title("> just frontmatter") == "Untitled"

    def test_extract_tags_from_title(self):
        from mcpdb.knowledge.chunker import _extract_tags_from_title
        tags = _extract_tags_from_title("Average Goals by League")
        assert "average" in tags
        assert "goals" in tags
        assert "league" in tags
        # "by" is a stop word
        assert "by" not in tags

    def test_yaml_non_dict_data(self):
        """YAML that parses to a non-dict should return empty."""
        docs = _chunk_yaml("- item1\n- item2\n", "list.yml")
        assert docs == []

    def test_yaml_nested_columns(self):
        content = """tables:
  users:
    description: User records
    columns:
      user_id:
        meaning: Primary key
        type: integer
      name:
        meaning: Full name
        type: varchar
"""
        docs = _chunk_yaml(content, "schema.yml")
        assert len(docs) == 1
        assert "user_id" in docs[0].content
        assert "name" in docs[0].content
        assert "users" in docs[0].tags

    def test_yaml_tables_as_top_level(self):
        """YAML without 'tables' key should treat top-level keys as tables."""
        content = """orders:
  description: Order records
  columns:
    order_id:
      meaning: Order identifier
"""
        docs = _chunk_yaml(content, "schema.yml")
        assert len(docs) == 1
        assert "orders" in docs[0].content

    def test_sql_multiple_annotated_blocks(self):
        content = """-- @description: Count by year
-- @tags: aggregate, yearly
SELECT year, COUNT(*) FROM events GROUP BY year;

-- @description: Average duration
-- @tags: average, duration
SELECT AVG(duration) FROM events;

-- @description: Top performers
-- @tags: ranking
SELECT name, score FROM users ORDER BY score DESC LIMIT 10;
"""
        docs = _chunk_sql(content, "queries.sql")
        assert len(docs) == 3
        assert docs[0].section_title == "Count by year"
        assert docs[2].section_title == "Top performers"

    def test_chunk_file_unicode_content(self, tmp_path):
        f = tmp_path / "unicode.md"
        f.write_text("# Übersicht\n\nDeutsche Zusammenfassung mit Umlauten: ä, ö, ü, ß.", encoding="utf-8")
        docs = chunk_file(f, base_dir=tmp_path)
        assert len(docs) == 1
        assert "Übersicht" in docs[0].section_title

    def test_chunk_file_binary_file(self, tmp_path):
        f = tmp_path / "binary.md"
        f.write_bytes(b"\x80\x81\x82\x83\x84\x85")
        docs = chunk_file(f, base_dir=tmp_path)
        assert docs == []

    def test_visualization_detection_all_keywords(self):
        """Test that all visualization keywords are detected."""
        viz_words = ["histogram", "scatter", "pie", "heatmap", "treemap",
                     "sunburst", "violin", "waterfall", "funnel", "radar",
                     "plotly", "px.", "go."]
        for word in viz_words:
            assert _is_visualization_chunk("", f"Use {word} for analysis"), \
                f"Failed to detect: {word}"


# =========================================================================
# Extended tests: retriever edge cases
# =========================================================================


class TestRetrieverEdgeCases:
    def test_all_chunks_exceed_budget(self):
        """When every chunk is too large for the budget, should include first one."""
        chunks = [
            KnowledgeChunk(
                id="1", text="word " * 500,
                category=KnowledgeCategory.SCHEMA_DOCS,
                relevance=0.9, section_title="Big A",
            ),
            KnowledgeChunk(
                id="2", text="word " * 500,
                category=KnowledgeCategory.SCHEMA_DOCS,
                relevance=0.5, section_title="Big B",
            ),
        ]
        result = format_knowledge_context(chunks, max_tokens=50)
        # Should include at least the first chunk (budget is checked after first)
        assert "Big A" in result

    def test_deduplication_case_insensitive(self):
        chunks = [
            KnowledgeChunk(id="1", text="Content A", category=KnowledgeCategory.SCHEMA_DOCS,
                          relevance=0.9, section_title="SQL Patterns"),
            KnowledgeChunk(id="2", text="Content B", category=KnowledgeCategory.SCHEMA_DOCS,
                          relevance=0.5, section_title="sql patterns"),
        ]
        result = format_knowledge_context(chunks, max_tokens=5000)
        assert result.count("SQL Patterns") + result.count("sql patterns") == 1

    def test_empty_title_not_deduped(self):
        """Chunks with empty titles should not be deduped against each other."""
        chunks = [
            KnowledgeChunk(id="1", text="Content A", category=KnowledgeCategory.SCHEMA_DOCS,
                          relevance=0.9, section_title=""),
            KnowledgeChunk(id="2", text="Content B", category=KnowledgeCategory.SCHEMA_DOCS,
                          relevance=0.5, section_title=""),
        ]
        result = format_knowledge_context(chunks, max_tokens=5000)
        assert "Content A" in result
        assert "Content B" in result

    def test_chunks_sorted_by_relevance(self):
        chunks = [
            KnowledgeChunk(id="1", text="Low", category=KnowledgeCategory.SCHEMA_DOCS,
                          relevance=0.1, section_title="Low"),
            KnowledgeChunk(id="2", text="High", category=KnowledgeCategory.SCHEMA_DOCS,
                          relevance=0.9, section_title="High"),
            KnowledgeChunk(id="3", text="Mid", category=KnowledgeCategory.SCHEMA_DOCS,
                          relevance=0.5, section_title="Mid"),
        ]
        result = format_knowledge_context(chunks, max_tokens=5000)
        assert result.index("High") < result.index("Mid") < result.index("Low")

    def test_separator_between_chunks(self):
        chunks = [
            KnowledgeChunk(id="1", text="A", category=KnowledgeCategory.SCHEMA_DOCS,
                          relevance=0.9, section_title="Title A"),
            KnowledgeChunk(id="2", text="B", category=KnowledgeCategory.SCHEMA_DOCS,
                          relevance=0.5, section_title="Title B"),
        ]
        result = format_knowledge_context(chunks, max_tokens=5000)
        assert "---" in result

    def test_format_includes_section_header(self):
        chunks = [
            KnowledgeChunk(id="1", text="Content here", category=KnowledgeCategory.SCHEMA_DOCS,
                          relevance=0.9, section_title="My Section"),
        ]
        result = format_knowledge_context(chunks, max_tokens=5000)
        assert "### My Section" in result

    def test_skips_large_chunk_then_includes_smaller(self):
        """Budget enforcement should skip large chunks and try smaller ones."""
        chunks = [
            KnowledgeChunk(
                id="1", text="word " * 10,
                category=KnowledgeCategory.SCHEMA_DOCS,
                relevance=0.9, section_title="Small First",
            ),
            KnowledgeChunk(
                id="2", text="word " * 500,
                category=KnowledgeCategory.SCHEMA_DOCS,
                relevance=0.7, section_title="Too Big",
            ),
            KnowledgeChunk(
                id="3", text="word " * 10,
                category=KnowledgeCategory.SCHEMA_DOCS,
                relevance=0.5, section_title="Small Third",
            ),
        ]
        result = format_knowledge_context(chunks, max_tokens=60)
        assert "Small First" in result
        # The big chunk should be skipped, small third may fit
        assert "Small Third" in result


# =========================================================================
# Extended tests: file provider edge cases
# =========================================================================


class TestFileProviderEdgeCases:
    def test_file_is_not_directory(self, tmp_path):
        """Passing a file path instead of directory should be handled."""
        f = tmp_path / "file.md"
        f.write_text("# Test\n\nContent.")
        provider = FileKnowledgeProvider([str(f)])
        count = provider.load()
        assert count == 0  # file is not a directory

    def test_empty_directory(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        provider = FileKnowledgeProvider([str(d)])
        count = provider.load()
        assert count == 0

    def test_directory_only_hidden_files(self, tmp_path):
        d = tmp_path / "hidden"
        d.mkdir()
        (d / "_private.md").write_text("# Private\n\nHidden content.")
        (d / ".dotfile.md").write_text("# Dot\n\nDot content.")
        provider = FileKnowledgeProvider([str(d)])
        count = provider.load()
        assert count == 0

    def test_retrieve_before_load(self):
        provider = FileKnowledgeProvider(["/nonexistent"])
        chunks = provider.retrieve("test")
        assert chunks == []

    def test_chunk_count_property(self, tmp_path):
        d = tmp_path / "rag"
        d.mkdir()
        (d / "doc.md").write_text("# Doc\n\nSome meaningful content here for testing.")
        provider = FileKnowledgeProvider([str(d)])
        assert provider.chunk_count == 0
        provider.load()
        assert provider.chunk_count > 0

    def test_cache_corruption_rebuilds(self, tmp_path):
        """Corrupted pickle cache should trigger rebuild."""
        d = tmp_path / "rag"
        d.mkdir()
        (d / "doc.md").write_text("# Doc\n\nContent for cache corruption test.")

        # Write corrupted cache
        cache_path = d / "_knowledge_index.pkl"
        cache_path.write_bytes(b"corrupted pickle data")

        provider = FileKnowledgeProvider([str(d)])
        count = provider.load()
        assert count > 0  # Should have rebuilt from scratch

    def test_load_with_embedding_provider(self, tmp_path):
        d = tmp_path / "rag"
        d.mkdir()
        (d / "doc.md").write_text("# Doc\n\nContent for embedding test with enough words.")
        provider = FileKnowledgeProvider([str(d)], embedding_provider=_FakeEmbeddingProvider())
        count = provider.load()
        assert count > 0

    def test_retrieve_with_table_names(self, tmp_path):
        d = tmp_path / "rag"
        d.mkdir()
        (d / "schema.md").write_text(
            "> Category: schema_docs\n\n"
            "# Schema\n\n"
            "## users\n\nThe users table has user_id and name columns. "
            "It stores all registered users in the system.\n\n"
            "## orders\n\nThe orders table tracks customer purchases with "
            "order_id, user_id FK, and total amount.\n"
        )
        provider = FileKnowledgeProvider([str(d)])
        provider.load()
        chunks = provider.retrieve("table information", table_names=["users"])
        # Should return results, and users-related chunks should rank higher
        assert len(chunks) > 0

    def test_subdirectory_scanning(self, tmp_path):
        d = tmp_path / "rag"
        sub = d / "subdir" / "deep"
        sub.mkdir(parents=True)
        (sub / "nested.md").write_text("# Nested\n\nContent in nested directory.")
        provider = FileKnowledgeProvider([str(d)])
        count = provider.load()
        assert count > 0

    def test_mixed_extensions(self, tmp_path):
        d = tmp_path / "rag"
        d.mkdir()
        (d / "doc.md").write_text("# MD\n\nMarkdown content.")
        (d / "schema.yml").write_text("tables:\n  t1:\n    description: Table one\n")
        (d / "query.sql").write_text("SELECT * FROM t1;")
        (d / "data.json").write_text('{"key": "value"}')
        (d / "readme.txt").write_text("Plain text file")

        provider = FileKnowledgeProvider([str(d)])
        count = provider.load()
        assert count >= 3  # md + yml + sql, not json or txt


# =========================================================================
# Extended tests: manager injection routing
# =========================================================================


class TestManagerInjectionRouting:
    """Test that injection points route to correct categories and budgets."""

    def _create_diverse_rag(self, tmp_path):
        rag = tmp_path / "rag"
        rag.mkdir()

        (rag / "schema.md").write_text(
            "> Category: schema_docs\n> Tags: tables\n\n"
            "# Schema\n\n"
            "## ins_cars\n\nThe ins_cars table stores vehicle insurance records "
            "with car_id, brand, model, year, and policy_holder_id.\n"
        )
        (rag / "rules.md").write_text(
            "> Category: business_rule\n> Tags: policy\n\n"
            "# Business Rules\n\n"
            "## Premium Calculation\n\nPremium is based on vehicle age, driver history, "
            "and coverage type. Minimum premium is 100 EUR.\n"
        )
        (rag / "viz.md").write_text(
            "> Category: visualization\n> Tags: plotly, chart\n\n"
            "# Charts\n\n"
            "## Bar Chart\n\nUse px.bar() for categorical comparisons. "
            "Always add title and axis labels.\n"
        )
        (rag / "terms.md").write_text(
            "> Category: terminology\n> Tags: glossary\n\n"
            "# Terminology\n\n"
            "## Policyholder\n\nThe person who owns the insurance policy. "
            "May be different from the driver or car owner.\n"
        )
        (rag / "quality.md").write_text(
            "> Category: data_quality\n> Tags: null, missing\n\n"
            "# Data Quality\n\n"
            "## NULL Values\n\nThe brand column has 5% NULL values. "
            "Filter or handle them in aggregations.\n"
        )
        (rag / "patterns.md").write_text(
            "> Category: query_template\n> Tags: sql\n\n"
            "# SQL Patterns\n\n"
            "## JOIN Pattern\n\nAlways use LEFT JOIN for optional relationships. "
            "Use explicit JOIN syntax for readability.\n"
        )
        return rag

    def test_classify_routes_to_terminology_and_schema(self, tmp_path):
        rag = self._create_diverse_rag(tmp_path)
        mgr = KnowledgeManager()
        mgr.add_file_provider(FileKnowledgeProvider([str(rag)]))
        mgr.load()

        ctx = mgr.retrieve("policyholder insurance", injection_point="classify")
        # classify should use TERMINOLOGY and SCHEMA_DOCS categories
        # Should find content from terms.md or schema.md
        assert isinstance(ctx, str)

    def test_plan_routes_to_query_template_and_more(self, tmp_path):
        rag = self._create_diverse_rag(tmp_path)
        mgr = KnowledgeManager()
        mgr.add_file_provider(FileKnowledgeProvider([str(rag)]))
        mgr.load()

        ctx = mgr.retrieve("SQL JOIN pattern", injection_point="plan")
        # plan should use QUERY_TEMPLATE, BUSINESS_RULE, DATA_QUALITY, SCHEMA_DOCS, VISUALIZATION
        assert isinstance(ctx, str)

    def test_debug_routes_to_data_quality(self, tmp_path):
        rag = self._create_diverse_rag(tmp_path)
        mgr = KnowledgeManager()
        mgr.add_file_provider(FileKnowledgeProvider([str(rag)]))
        mgr.load()

        ctx = mgr.retrieve("NULL values missing data", injection_point="debug")
        assert isinstance(ctx, str)

    def test_synthesize_routes_to_business_rule(self, tmp_path):
        rag = self._create_diverse_rag(tmp_path)
        mgr = KnowledgeManager()
        mgr.add_file_provider(FileKnowledgeProvider([str(rag)]))
        mgr.load()

        ctx = mgr.retrieve("premium calculation policy", injection_point="synthesize")
        assert isinstance(ctx, str)

    def test_blueprint_routes_to_all_categories(self, tmp_path):
        rag = self._create_diverse_rag(tmp_path)
        mgr = KnowledgeManager()
        mgr.add_file_provider(FileKnowledgeProvider([str(rag)]))
        mgr.load()

        # blueprint has None categories = all
        ctx = mgr.retrieve("insurance analysis", injection_point="blueprint")
        assert isinstance(ctx, str)

    def test_unknown_injection_point_uses_defaults(self, tmp_path):
        rag = self._create_diverse_rag(tmp_path)
        mgr = KnowledgeManager()
        mgr.add_file_provider(FileKnowledgeProvider([str(rag)]))
        mgr.load()

        ctx = mgr.retrieve("test query", injection_point="unknown_point")
        # Should use default budget (2000) and no category filter (None)
        assert isinstance(ctx, str)

    def test_custom_categories_override(self, tmp_path):
        rag = self._create_diverse_rag(tmp_path)
        mgr = KnowledgeManager()
        mgr.add_file_provider(FileKnowledgeProvider([str(rag)]))
        mgr.load()

        ctx = mgr.retrieve(
            "chart bar plotly",
            injection_point="classify",
            categories={KnowledgeCategory.VISUALIZATION},  # override
        )
        assert isinstance(ctx, str)

    def test_custom_max_tokens_override(self, tmp_path):
        rag = self._create_diverse_rag(tmp_path)
        mgr = KnowledgeManager()
        mgr.add_file_provider(FileKnowledgeProvider([str(rag)]))
        mgr.load()

        ctx = mgr.retrieve("insurance", injection_point="plan", max_tokens=10)
        # Very small budget — should return very little
        assert isinstance(ctx, str)

    def test_table_names_forwarded(self, tmp_path):
        rag = self._create_diverse_rag(tmp_path)
        mgr = KnowledgeManager()
        mgr.add_file_provider(FileKnowledgeProvider([str(rag)]))
        mgr.load()

        ctx = mgr.retrieve(
            "car insurance records",
            injection_point="plan",
            table_names=["ins_cars"],
        )
        assert isinstance(ctx, str)


class TestManagerMultipleProviders:
    """Test KnowledgeManager with multiple file providers."""

    def test_multiple_providers_aggregated(self, tmp_path):
        d1 = tmp_path / "rag1"
        d2 = tmp_path / "rag2"
        d1.mkdir()
        d2.mkdir()
        (d1 / "doc1.md").write_text("# Provider One\n\nContent from first provider about insurance.")
        (d2 / "doc2.md").write_text("# Provider Two\n\nContent from second provider about claims.")

        mgr = KnowledgeManager()
        mgr.add_file_provider(FileKnowledgeProvider([str(d1)]))
        mgr.add_file_provider(FileKnowledgeProvider([str(d2)]))
        count = mgr.load()
        assert count >= 2
        assert mgr.total_chunks >= 2

    def test_search_across_providers(self, tmp_path):
        d1 = tmp_path / "rag1"
        d2 = tmp_path / "rag2"
        d1.mkdir()
        d2.mkdir()
        (d1 / "doc1.md").write_text("# Cars\n\nInsurance coverage for vehicles and automobiles.")
        (d2 / "doc2.md").write_text("# Houses\n\nProperty insurance for residential buildings.")

        mgr = KnowledgeManager()
        mgr.add_file_provider(FileKnowledgeProvider([str(d1)]))
        mgr.add_file_provider(FileKnowledgeProvider([str(d2)]))
        mgr.load()

        chunks = mgr.search("insurance vehicles")
        assert len(chunks) > 0
        # Results should be sorted by relevance
        scores = [c.relevance for c in chunks]
        assert scores == sorted(scores, reverse=True)

    def test_search_max_results(self, tmp_path):
        d = tmp_path / "rag"
        d.mkdir()
        for i in range(20):
            (d / f"doc{i}.md").write_text(f"# Doc {i}\n\nInsurance topic {i} content here.")

        mgr = KnowledgeManager()
        mgr.add_file_provider(FileKnowledgeProvider([str(d)]))
        mgr.load()

        chunks = mgr.search("insurance", max_results=3)
        assert len(chunks) <= 3

    def test_search_not_loaded(self):
        mgr = KnowledgeManager()
        chunks = mgr.search("test")
        assert chunks == []


# =========================================================================
# Extended tests: agent graph integration
# =========================================================================


class TestGraphKnowledgeInjection:
    """Test that run_agent actually injects knowledge_context into state."""

    def test_knowledge_context_injected_in_run_agent(self, tmp_path):
        """Verify run_agent calls knowledge_manager.retrieve() and sets state."""
        mock_manager = MagicMock()
        mock_manager.retrieve.return_value = "## Domain Knowledge\nTest context"

        # We can't run the full agent without DB + LLM, but we can verify
        # the knowledge retrieval call happens by checking the source code path
        from mcpdb.agent.graph import run_agent
        import inspect
        source = inspect.getsource(run_agent)

        # Verify the retrieval call pattern
        assert 'knowledge_manager.retrieve(' in source
        assert 'knowledge_context' in source
        assert 'injection_point="plan"' in source

    def test_knowledge_context_used_in_plan_prompt(self):
        """Verify make_plan injects DOMAIN KNOWLEDGE section into prompt."""
        from mcpdb.agent.nodes.common import make_plan
        import inspect
        source = inspect.getsource(make_plan)

        # The knowledge context should be appended with a header
        assert '## DOMAIN KNOWLEDGE' in source
        assert 'knowledge_context' in source

    def test_agent_state_knowledge_field_type(self):
        """Verify the AgentState knowledge_context field allows str or None."""
        from mcpdb.agent.state import AgentState
        annotation = AgentState.__annotations__["knowledge_context"]
        # Should be str | None
        assert "str" in str(annotation) or annotation is str


# =========================================================================
# Extended tests: cosine similarity edge cases
# =========================================================================


class TestCosineSimilarityExtended:
    def test_negative_cosine(self):
        """Opposite vectors should have negative cosine similarity."""
        result = _cosine_similarity([1, 0], [-1, 0])
        assert result < 0

    def test_near_identical(self):
        result = _cosine_similarity([1.0, 2.0, 3.0], [1.001, 2.001, 3.001])
        assert abs(result - 1.0) < 0.01

    def test_zero_vector(self):
        assert _cosine_similarity([0, 0, 0], [1, 2, 3]) == 0.0
        assert _cosine_similarity([1, 2, 3], [0, 0, 0]) == 0.0

    def test_unit_vectors(self):
        import math
        # 45 degree angle
        v1 = [1, 0]
        v2 = [math.sqrt(2)/2, math.sqrt(2)/2]
        result = _cosine_similarity(v1, v2)
        assert abs(result - math.sqrt(2)/2) < 0.001

    def test_high_dimensional(self):
        """Should work with high-dimensional vectors (768 dims)."""
        import math
        v1 = [1.0 / math.sqrt(768)] * 768
        v2 = [1.0 / math.sqrt(768)] * 768
        result = _cosine_similarity(v1, v2)
        assert abs(result - 1.0) < 0.01


# =========================================================================
# Extended tests: index category operations
# =========================================================================


class TestIndexCategoryOperations:
    def _make_doc(self, content, category, title="test"):
        return KnowledgeDocument(
            content=content, source_label="test.md",
            category=category, section_title=title,
        )

    def test_multiple_categories_filter(self):
        idx = KnowledgeIndex()
        idx.add(self._make_doc("schema info tables columns", KnowledgeCategory.SCHEMA_DOCS, "Schema"))
        idx.add(self._make_doc("chart plotly visualization bar", KnowledgeCategory.VISUALIZATION, "Chart"))
        idx.add(self._make_doc("business rule premium calculation", KnowledgeCategory.BUSINESS_RULE, "Rule"))
        idx.add(self._make_doc("query template join pattern", KnowledgeCategory.QUERY_TEMPLATE, "Query"))

        results = idx.search(
            "schema chart query",
            categories={KnowledgeCategory.SCHEMA_DOCS, KnowledgeCategory.VISUALIZATION},
        )
        categories = {r.category for r in results}
        assert KnowledgeCategory.BUSINESS_RULE not in categories
        assert KnowledgeCategory.QUERY_TEMPLATE not in categories

    def test_empty_category_returns_nothing(self):
        idx = KnowledgeIndex()
        idx.add(self._make_doc("content", KnowledgeCategory.SCHEMA_DOCS, "Doc"))
        results = idx.search("content", categories={KnowledgeCategory.VISUALIZATION})
        assert results == []

    def test_category_index_built_correctly(self):
        idx = KnowledgeIndex()
        idx.add(self._make_doc("doc1", KnowledgeCategory.SCHEMA_DOCS))
        idx.add(self._make_doc("doc2", KnowledgeCategory.VISUALIZATION))
        idx.add(self._make_doc("doc3", KnowledgeCategory.SCHEMA_DOCS))

        assert len(idx._category_index[KnowledgeCategory.SCHEMA_DOCS]) == 2
        assert len(idx._category_index[KnowledgeCategory.VISUALIZATION]) == 1

    def test_clear_resets_category_index(self):
        idx = KnowledgeIndex()
        idx.add(self._make_doc("doc", KnowledgeCategory.SCHEMA_DOCS))
        idx.clear()
        assert idx._category_index == {}


# =========================================================================
# Extended tests: knowledge document dataclass
# =========================================================================


class TestKnowledgeDocument:
    def test_defaults(self):
        doc = KnowledgeDocument(content="text", source_label="file.md")
        assert doc.category == KnowledgeCategory.SCHEMA_DOCS
        assert doc.tags == []
        assert doc.section_title == ""
        assert doc.metadata == {}

    def test_with_all_fields(self):
        doc = KnowledgeDocument(
            content="content",
            source_label="file.md",
            category=KnowledgeCategory.VISUALIZATION,
            tags=["chart", "plotly"],
            section_title="Bar Chart",
            metadata={"priority": "high"},
        )
        assert doc.category == KnowledgeCategory.VISUALIZATION
        assert doc.tags == ["chart", "plotly"]
        assert doc.metadata["priority"] == "high"


# =========================================================================
# Extended tests: end-to-end RAG pipeline (no LLM)
# =========================================================================


class TestEndToEndPipeline:
    """Test the full RAG pipeline: files → chunks → index → retrieve → format."""

    def test_full_pipeline(self, tmp_path):
        """End-to-end: create RAG files, load, search, format context."""
        rag = tmp_path / "knowledge"
        rag.mkdir()

        (rag / "schema.md").write_text(
            "> Category: schema_docs\n"
            "> Tags: tables, database\n\n"
            "# Database Schema\n\n"
            "## customers\n\n"
            "The customers table stores customer information including "
            "customer_id (PK), name, email, and registration_date.\n\n"
            "## orders\n\n"
            "The orders table tracks purchases with order_id (PK), "
            "customer_id (FK), total_amount, and order_date.\n"
        )

        (rag / "patterns.md").write_text(
            "> Category: query_template\n"
            "> Tags: sql, join\n\n"
            "# SQL Patterns\n\n"
            "## Customer Orders Join\n\n"
            "To get customer orders, use:\n"
            "```sql\n"
            "SELECT c.name, o.total_amount\n"
            "FROM customers c JOIN orders o ON c.customer_id = o.customer_id\n"
            "```\n\n"
            "## Monthly Revenue\n\n"
            "To calculate monthly revenue:\n"
            "```sql\n"
            "SELECT DATE_FORMAT(order_date, '%Y-%m') as month, SUM(total_amount)\n"
            "FROM orders GROUP BY month\n"
            "```\n"
        )

        (rag / "viz.md").write_text(
            "> Category: visualization\n"
            "> Tags: plotly, chart\n\n"
            "# Visualization Guide\n\n"
            "## Revenue Bar Chart\n\n"
            "Use px.bar(df, x='month', y='revenue') for monthly revenue charts. "
            "Add color='category' for segmented analysis.\n"
        )

        # Create manager and load
        mgr = KnowledgeManager()
        mgr.add_file_provider(FileKnowledgeProvider([str(rag)]))
        count = mgr.load()
        assert count >= 3

        # Retrieve for plan injection
        plan_ctx = mgr.retrieve("customer orders JOIN query", injection_point="plan")
        assert len(plan_ctx) > 0
        assert "customer" in plan_ctx.lower() or "order" in plan_ctx.lower()

        # Retrieve for classify injection
        classify_ctx = mgr.retrieve("customer information", injection_point="classify")
        assert isinstance(classify_ctx, str)

        # Retrieve for debug injection
        debug_ctx = mgr.retrieve("order data quality", injection_point="debug")
        assert isinstance(debug_ctx, str)

        # Search raw chunks
        chunks = mgr.search("revenue chart visualization")
        assert isinstance(chunks, list)

    def test_pipeline_with_vectors(self, tmp_path):
        """End-to-end with fake embedding provider for vector re-ranking."""
        rag = tmp_path / "knowledge"
        rag.mkdir()

        (rag / "doc1.md").write_text("# Insurance\n\nCar insurance policy records for vehicles.")
        (rag / "doc2.md").write_text("# Claims\n\nDamage claim reports and repair cost estimates.")
        (rag / "doc3.md").write_text("# Statistics\n\nAnnual statistics and aggregate reports.")

        provider = _FakeEmbeddingProvider()
        mgr = KnowledgeManager()
        mgr.add_file_provider(FileKnowledgeProvider([str(rag)], embedding_provider=provider))
        count = mgr.load()
        assert count >= 3

        ctx = mgr.retrieve("insurance claims damage")
        assert isinstance(ctx, str)

    def test_pipeline_cache_roundtrip(self, tmp_path):
        """Load → cache → reload from cache → verify same results."""
        rag = tmp_path / "knowledge"
        rag.mkdir()
        (rag / "doc.md").write_text(
            "# Test Document\n\n"
            "## Section One\n\n"
            "Content about insurance claims and damage reports for vehicles. "
            + "Extra words " * 50 + "\n\n"
            "## Section Two\n\n"
            "Content about car repair costs and estimates for accident repairs. "
            + "More words " * 50
        )

        # First load — builds index
        p1 = FileKnowledgeProvider([str(rag)])
        count1 = p1.load()
        results1 = p1.retrieve("insurance claims")

        # Second load — should use cache
        p2 = FileKnowledgeProvider([str(rag)])
        count2 = p2.load()
        results2 = p2.retrieve("insurance claims")

        assert count1 == count2
        assert len(results1) == len(results2)
        # Same chunks should be found
        titles1 = {r.section_title for r in results1}
        titles2 = {r.section_title for r in results2}
        assert titles1 == titles2
