"""Markdown chunker — splits RAG files into indexable knowledge documents."""

from __future__ import annotations

import re
from pathlib import Path

from mcpdb.knowledge.base import KnowledgeCategory, KnowledgeDocument, resolve_category


def chunk_markdown(
    content: str,
    source_label: str,
    default_category: KnowledgeCategory = KnowledgeCategory.SCHEMA_DOCS,
) -> list[KnowledgeDocument]:
    """Split markdown by ## and ### headings into knowledge documents.

    Parsing rules:
    1. Extract frontmatter (> Tags:, > Category:, > Priority:) from file header
    2. Split on ## headings first
    3. If a ## section has ### subsections, split further on ###
    4. Each chunk inherits the file's frontmatter category and tags
    5. Small files (<500 tokens) are kept as a single chunk
    """
    # Parse frontmatter from first lines
    file_tags: list[str] = []
    file_category = default_category
    header_end = 0

    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("> Tags:") or stripped.startswith("> tags:"):
            raw_tags = stripped.split(":", 1)[1].strip()
            file_tags = [t.strip().lower() for t in raw_tags.split(",") if t.strip()]
        elif stripped.startswith("> Category:") or stripped.startswith("> category:"):
            raw_cat = stripped.split(":", 1)[1].strip()
            file_category = resolve_category(raw_cat)
        elif stripped.startswith("> ") or stripped.startswith("# ") or not stripped:
            continue
        else:
            break

    # Detect category from directory path
    if "/" in source_label:
        dir_part = source_label.split("/")[0].lower()
        dir_categories: dict[str, KnowledgeCategory] = {
            "python": KnowledgeCategory.QUERY_TEMPLATE,
            "domain": KnowledgeCategory.SCHEMA_DOCS,
            "working_scenarios": KnowledgeCategory.WORKING_EXAMPLE,
            "questions": KnowledgeCategory.QA,
            "dataset_specific": KnowledgeCategory.QA,
            "patterns": KnowledgeCategory.QUERY_TEMPLATE,
            "templates": KnowledgeCategory.QUERY_TEMPLATE,
        }
        if dir_part in dir_categories and file_category == KnowledgeCategory.SCHEMA_DOCS:
            file_category = dir_categories[dir_part]

    # Further refine category based on tags
    if file_category == KnowledgeCategory.QUERY_TEMPLATE:
        viz_keywords = {"plotly", "chart", "visualization", "histogram", "scatter", "bar"}
        if viz_keywords & set(file_tags):
            file_category = KnowledgeCategory.VISUALIZATION

    # Small file → single chunk
    word_count = len(content.split())
    if word_count < 400:
        return [KnowledgeDocument(
            content=content.strip(),
            source_label=source_label,
            category=file_category,
            tags=file_tags,
            section_title=_extract_title(content),
        )]

    # Split on ## headings
    sections = _split_on_headings(content, level=2)

    # If only one section (no ## headings), try ### headings
    if len(sections) <= 1:
        sections = _split_on_headings(content, level=3)

    # If still no sections, return whole file
    if len(sections) <= 1:
        return [KnowledgeDocument(
            content=content.strip(),
            source_label=source_label,
            category=file_category,
            tags=file_tags,
            section_title=_extract_title(content),
        )]

    documents: list[KnowledgeDocument] = []
    for title, body in sections:
        chunk_text = body.strip()
        if not chunk_text or len(chunk_text.split()) < 10:
            continue

        # If this ## section is large and has ### subsections, split further
        sub_sections = _split_on_headings(chunk_text, level=3)
        if len(sub_sections) > 1 and len(chunk_text.split()) > 600:
            for sub_title, sub_body in sub_sections:
                sub_text = sub_body.strip()
                if not sub_text or len(sub_text.split()) < 10:
                    continue

                # Detect visualization category for specific chart sections
                chunk_cat = file_category
                if _is_visualization_chunk(sub_title, sub_text):
                    chunk_cat = KnowledgeCategory.VISUALIZATION

                documents.append(KnowledgeDocument(
                    content=sub_text,
                    source_label=source_label,
                    category=chunk_cat,
                    tags=file_tags + _extract_tags_from_title(sub_title),
                    section_title=sub_title,
                ))
        else:
            chunk_cat = file_category
            if _is_visualization_chunk(title, chunk_text):
                chunk_cat = KnowledgeCategory.VISUALIZATION

            documents.append(KnowledgeDocument(
                content=chunk_text,
                source_label=source_label,
                category=chunk_cat,
                tags=file_tags + _extract_tags_from_title(title),
                section_title=title,
            ))

    return documents if documents else [KnowledgeDocument(
        content=content.strip(),
        source_label=source_label,
        category=file_category,
        tags=file_tags,
        section_title=_extract_title(content),
    )]


def chunk_file(path: Path, base_dir: Path | None = None) -> list[KnowledgeDocument]:
    """Parse a file and return knowledge documents.

    Dispatches based on file extension (.md, .yml/.yaml, .sql).
    """
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    if not content.strip():
        return []

    # Build a relative source label
    if base_dir:
        try:
            source_label = str(path.relative_to(base_dir))
        except ValueError:
            source_label = path.name
    else:
        source_label = path.name

    ext = path.suffix.lower()
    if ext in (".md", ".markdown"):
        return chunk_markdown(content, source_label)
    elif ext in (".yml", ".yaml"):
        return _chunk_yaml(content, source_label)
    elif ext == ".sql":
        return _chunk_sql(content, source_label)

    return []


def _split_on_headings(text: str, level: int = 2) -> list[tuple[str, str]]:
    """Split markdown text on headings of the given level.

    Returns list of (title, body) tuples.
    """
    prefix = "#" * level + " "
    pattern = re.compile(rf"^{re.escape(prefix)}(.+)$", re.MULTILINE)

    matches = list(pattern.finditer(text))
    if not matches:
        return [(_extract_title(text), text)]

    sections: list[tuple[str, str]] = []

    # Content before first heading (if any meaningful content)
    pre = text[:matches[0].start()].strip()
    if pre and len(pre.split()) > 20:
        sections.append((_extract_title(pre), pre))

    for i, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        sections.append((title, body))

    return sections


def _extract_title(text: str) -> str:
    """Extract the first heading or first meaningful line as title."""
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
        if stripped.startswith(">"):
            continue
        if stripped and len(stripped) > 5:
            return stripped[:100]
    return "Untitled"


def _extract_tags_from_title(title: str) -> list[str]:
    """Extract keyword tags from a section title."""
    words = re.findall(r"[a-z0-9_]+", title.lower())
    stop = {"the", "a", "an", "by", "for", "and", "or", "vs", "with", "from", "to", "in", "of"}
    return [w for w in words if w not in stop and len(w) > 2]


def _is_visualization_chunk(title: str, text: str) -> bool:
    """Detect if a chunk is about visualization/charts."""
    viz_keywords = {
        "chart", "plot", "histogram", "scatter", "bar", "pie", "donut",
        "heatmap", "treemap", "sunburst", "violin", "waterfall", "funnel",
        "radar", "timeline", "gantt", "kpi", "indicator", "pareto",
        "plotly", "px.", "go.", "fig.", "apply_style",
    }
    combined = (title + " " + text[:500]).lower()
    return any(kw in combined for kw in viz_keywords)


def _chunk_yaml(content: str, source_label: str) -> list[KnowledgeDocument]:
    """Parse YAML data dictionary into knowledge documents."""
    try:
        import yaml
        data = yaml.safe_load(content)
    except Exception:
        return [KnowledgeDocument(
            content=content,
            source_label=source_label,
            category=KnowledgeCategory.SCHEMA_DOCS,
            section_title=source_label,
        )]

    if not isinstance(data, dict):
        return []

    documents: list[KnowledgeDocument] = []
    tables = data.get("tables", data)
    if isinstance(tables, dict):
        for table_name, table_info in tables.items():
            if isinstance(table_info, dict):
                desc = table_info.get("description", "")
                cols = table_info.get("columns", {})
                parts = [f"Table: {table_name}"]
                if desc:
                    parts.append(f"Description: {desc}")
                if isinstance(cols, dict):
                    for col_name, col_info in cols.items():
                        if isinstance(col_info, dict):
                            meaning = col_info.get("meaning", "")
                            parts.append(f"  {col_name}: {meaning}")
                        else:
                            parts.append(f"  {col_name}: {col_info}")

                documents.append(KnowledgeDocument(
                    content="\n".join(parts),
                    source_label=source_label,
                    category=KnowledgeCategory.SCHEMA_DOCS,
                    tags=[table_name.lower()],
                    section_title=f"Table: {table_name}",
                ))

    return documents


def _chunk_sql(content: str, source_label: str) -> list[KnowledgeDocument]:
    """Parse annotated SQL file into knowledge documents."""
    # Split on -- @description: markers
    blocks = re.split(r"(?=^-- @description:)", content, flags=re.MULTILINE)
    documents: list[KnowledgeDocument] = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        desc_match = re.search(r"^-- @description:\s*(.+)$", block, re.MULTILINE)
        tags_match = re.search(r"^-- @tags:\s*(.+)$", block, re.MULTILINE)

        title = desc_match.group(1).strip() if desc_match else source_label
        tags = []
        if tags_match:
            tags = [t.strip().lower() for t in tags_match.group(1).split(",")]

        documents.append(KnowledgeDocument(
            content=block,
            source_label=source_label,
            category=KnowledgeCategory.QUERY_TEMPLATE,
            tags=tags,
            section_title=title,
        ))

    return documents if documents else [KnowledgeDocument(
        content=content,
        source_label=source_label,
        category=KnowledgeCategory.QUERY_TEMPLATE,
        section_title=source_label,
    )]
