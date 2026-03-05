"""Source fingerprinting — stable identity hash per data source."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from mcpdb.sources.base import SourceMetadata


def fingerprint_source(metadata: SourceMetadata) -> str:
    """Generate a stable fingerprint for a data source.

    The fingerprint is based on source type + table names + column signatures,
    so that two connections to the same database produce the same fingerprint
    even if made at different times.
    """
    parts = [metadata.source_type.value]

    # Sort tables for determinism
    for table in sorted(metadata.tables, key=lambda t: t.name):
        col_sig = ",".join(
            f"{c.name}:{c.dtype}" for c in sorted(table.columns, key=lambda c: c.name)
        )
        parts.append(f"{table.name}({col_sig})")

    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def fingerprint_schema(metadata: SourceMetadata) -> str:
    """Generate a shorter schema hash for drift detection.

    Changes to table structure will change this hash.
    """
    parts = []
    for table in sorted(metadata.tables, key=lambda t: t.name):
        cols = ",".join(
            f"{c.name}:{c.dtype}" for c in sorted(table.columns, key=lambda c: c.name)
        )
        parts.append(f"{table.name}:{cols}")
    raw = "|".join(parts)
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def intent_hash(question: str, source_fingerprint: str) -> str:
    """Hash a question + source fingerprint for exact-match cache lookup."""
    normalized = question.strip().lower()
    raw = f"{normalized}|{source_fingerprint}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


# ---------------------------------------------------------------------------
# Semantic normalization — strips filler so differently-phrased questions
# that ask the same thing produce the same hash.
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset({
    # articles
    'a', 'an', 'the',
    # pronouns
    'i', 'me', 'my', 'mine', 'you', 'your', 'yours', 'we', 'our', 'us',
    'he', 'she', 'it', 'its', 'they', 'their', 'this', 'that', 'these', 'those',
    # prepositions
    'of', 'in', 'for', 'to', 'from', 'at', 'by', 'with', 'on', 'about', 'as',
    'into', 'through', 'between', 'after', 'before', 'above', 'below',
    # conjunctions
    'and', 'or', 'but', 'nor', 'so', 'yet',
    # modals / auxiliaries
    'please', 'can', 'could', 'would', 'should', 'will', 'shall',
    'do', 'does', 'did', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'having',
    # request verbs — these frame how the user asks, not *what* they ask
    'show', 'plot', 'draw', 'render', 'display', 'visualize', 'illustrate',
    'generate', 'create', 'make', 'build', 'produce', 'write', 'output',
    'give', 'provide', 'present', 'print', 'list', 'describe', 'explain',
    'get', 'fetch', 'retrieve', 'find', 'tell',
    # filler
    'want', 'need', 'like', 'just', 'also', 'very', 'really', 'quite',
    'now', 'then', 'here', 'there', 'some', 'any', 'all', 'each', 'every',
    'using', 'use',
})

# Normalize domain synonyms so "database schema" = "db schema", etc.
_SYNONYMS: dict[str, str] = {
    'database': 'db', 'databases': 'db',
    'tables': 'table',
    'columns': 'column', 'col': 'column', 'cols': 'column',
    'fields': 'field',
    'diagrams': 'diagram', 'chart': 'diagram', 'charts': 'diagram',
    'graph': 'diagram', 'graphs': 'diagram',
    'relationships': 'relationship', 'relations': 'relationship', 'relation': 'relationship',
    'entity': 'er', 'erd': 'er',
    'queries': 'query',
    'rows': 'row', 'records': 'record',
    'values': 'value',
    'counts': 'count', 'counting': 'count',
    'totals': 'total',
    'averages': 'average', 'avg': 'average', 'mean': 'average',
    'maximum': 'max', 'minimum': 'min',
}

_NON_ALPHA = re.compile(r'[^a-z0-9_]+')


def normalize_question(question: str) -> str:
    """Reduce a question to its semantic content words.

    Strips stopwords, normalizes synonyms, sorts alphabetically.
    Result is deterministic — same intent always produces the same string
    regardless of phrasing.
    """
    text = question.lower()
    tokens = _NON_ALPHA.split(text)
    kept = []
    for tok in tokens:
        if not tok or tok in _STOPWORDS:
            continue
        tok = _SYNONYMS.get(tok, tok)
        kept.append(tok)
    kept.sort()
    return ' '.join(kept)


def semantic_hash(question: str, source_fingerprint: str) -> str:
    """Hash normalized question + source fingerprint for fuzzy-match lookup.

    Two differently-phrased questions with the same intent produce the same hash.
    """
    normalized = normalize_question(question)
    raw = f"{normalized}|{source_fingerprint}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]
