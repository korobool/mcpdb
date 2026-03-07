"""CSV loader — encoding detection, delimiter detection, header detection."""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import chardet

logger = logging.getLogger("mcpdb.csv.loader")

# Common delimiters to try
_DELIMITERS = [",", ";", "\t", "|"]


@dataclass
class CsvLoadResult:
    """Result of detecting CSV file properties (no data loaded into memory)."""

    table_name: str
    file_path: str
    encoding: str
    delimiter: str
    has_header: bool
    row_count: int = 0
    column_count: int = 0
    columns: list[str] = field(default_factory=list)


def detect_encoding(file_path: str | Path, sample_size: int = 65536) -> str:
    """Detect file encoding using chardet."""
    with open(file_path, "rb") as f:
        raw = f.read(sample_size)
    result = chardet.detect(raw)
    encoding = result.get("encoding", "utf-8") or "utf-8"
    confidence = result.get("confidence", 0)
    logger.debug("Detected encoding '%s' (confidence=%.2f) for %s",
                 encoding, confidence, file_path)
    return encoding


def detect_delimiter(file_path: str | Path, encoding: str = "utf-8") -> str:
    """Detect CSV delimiter by sniffing the first few lines."""
    with open(file_path, "r", encoding=encoding, errors="replace") as f:
        sample = f.read(8192)

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(_DELIMITERS))
        return dialect.delimiter
    except csv.Error:
        pass

    # Fallback: count occurrences of common delimiters in first line
    first_line = sample.split("\n")[0] if sample else ""
    best_delim = ","
    best_count = 0
    for delim in _DELIMITERS:
        count = first_line.count(delim)
        if count > best_count:
            best_count = count
            best_delim = delim

    return best_delim


def detect_header(file_path: str | Path, encoding: str = "utf-8", delimiter: str = ",") -> bool:
    """Detect if the CSV file has a header row."""
    try:
        with open(file_path, "r", encoding=encoding, errors="replace") as f:
            sample = f.read(8192)
        return csv.Sniffer().has_header(sample)
    except csv.Error:
        # If sniffer fails, assume header exists (most common case)
        return True


def _make_table_name(file_path: str | Path) -> str:
    """Create a table name from a file path."""
    import re
    name = Path(file_path).stem
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if name and name[0].isdigit():
        name = f"csv_{name}"
    return name or "unnamed_csv"


def detect_csv(
    file_path: str | Path,
    table_name: str | None = None,
    encoding: str | None = None,
    delimiter: str | None = None,
    has_header: bool | None = None,
) -> CsvLoadResult:
    """Detect CSV file properties without loading data into memory.

    Args:
        file_path: Path to the CSV file.
        table_name: Override table name (default: derived from filename).
        encoding: Override encoding (default: auto-detect).
        delimiter: Override delimiter (default: auto-detect).
        has_header: Override header detection (default: auto-detect).

    Returns:
        CsvLoadResult with detected properties (no data loaded).
    """
    file_path = str(file_path)

    # Auto-detect
    if encoding is None:
        encoding = detect_encoding(file_path)
    if delimiter is None:
        delimiter = detect_delimiter(file_path, encoding)
    if has_header is None:
        has_header = detect_header(file_path, encoding, delimiter)

    tname = table_name or _make_table_name(file_path)

    logger.info("Detected CSV '%s': encoding=%s, delim=%r, header=%s",
                file_path, encoding, delimiter, has_header)

    return CsvLoadResult(
        table_name=tname,
        file_path=file_path,
        encoding=encoding,
        delimiter=delimiter,
        has_header=has_header,
    )


# Keep backwards-compatible alias
load_csv = detect_csv


def detect_multiple_csvs(
    file_paths: list[str | Path],
    table_names: list[str] | None = None,
) -> list[CsvLoadResult]:
    """Detect properties for multiple CSV files with unique table names."""
    results = []
    used_names: set[str] = set()

    for i, path in enumerate(file_paths):
        name = table_names[i] if table_names and i < len(table_names) else None
        result = detect_csv(path, table_name=name)

        # Ensure unique table name
        base = result.table_name
        suffix = 1
        while result.table_name in used_names:
            result.table_name = f"{base}_{suffix}"
            suffix += 1
        used_names.add(result.table_name)

        results.append(result)

    return results


# Keep backwards-compatible alias
load_multiple_csvs = detect_multiple_csvs
