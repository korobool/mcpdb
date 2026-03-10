"""Knowledge base types — chunks, categories, and provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class KnowledgeCategory(str, Enum):
    """Category tags for knowledge chunks."""

    SCHEMA_DOCS = "schema_docs"
    BUSINESS_RULE = "business_rule"
    QUERY_TEMPLATE = "query_template"
    DATA_QUALITY = "data_quality"
    TERMINOLOGY = "terminology"
    VISUALIZATION = "visualization"
    WORKING_EXAMPLE = "working_example"
    QA = "qa"


# Mapping from RAG frontmatter to categories
_CATEGORY_ALIASES: dict[str, KnowledgeCategory] = {
    "python_reference": KnowledgeCategory.QUERY_TEMPLATE,
    "sql_patterns": KnowledgeCategory.QUERY_TEMPLATE,
    "domain": KnowledgeCategory.SCHEMA_DOCS,
    "working_scenarios": KnowledgeCategory.WORKING_EXAMPLE,
    "qa": KnowledgeCategory.QA,
    "visualization": KnowledgeCategory.VISUALIZATION,
    "business_rule": KnowledgeCategory.BUSINESS_RULE,
    "data_quality": KnowledgeCategory.DATA_QUALITY,
    "terminology": KnowledgeCategory.TERMINOLOGY,
    "schema_docs": KnowledgeCategory.SCHEMA_DOCS,
    "query_template": KnowledgeCategory.QUERY_TEMPLATE,
}


def resolve_category(raw: str) -> KnowledgeCategory:
    """Resolve a category string to a KnowledgeCategory enum value."""
    key = raw.strip().lower().replace(" ", "_").replace("-", "_")
    if key in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[key]
    try:
        return KnowledgeCategory(key)
    except ValueError:
        return KnowledgeCategory.SCHEMA_DOCS


@dataclass
class KnowledgeChunk:
    """A retrieved piece of knowledge ready for prompt injection."""

    id: str
    text: str
    category: KnowledgeCategory
    relevance: float = 0.0
    tags: list[str] = field(default_factory=list)
    source_file: str = ""
    section_title: str = ""
    token_estimate: int = 0

    def __post_init__(self) -> None:
        if self.token_estimate == 0:
            self.token_estimate = int(len(self.text.split()) * 1.3)


@dataclass
class KnowledgeDocument:
    """A raw document to be indexed (intermediate repr between parsing and indexing)."""

    content: str
    source_label: str
    category: KnowledgeCategory = KnowledgeCategory.SCHEMA_DOCS
    tags: list[str] = field(default_factory=list)
    section_title: str = ""
    metadata: dict = field(default_factory=dict)


class EmbeddingProvider(ABC):
    """Abstract interface for text embedding."""

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list of float vectors."""
        ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a single query text."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimensionality of the embedding vectors."""
        ...

    def is_available(self) -> bool:
        """Whether this provider can actually produce embeddings."""
        return self.dimension > 0
