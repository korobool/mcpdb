"""SQL safety — read-only enforcement and injection prevention."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("mcpdb.security.sql")

# Patterns for write/destructive SQL statements
_WRITE_PATTERNS = [
    re.compile(r"\b(INSERT)\s+INTO\b", re.IGNORECASE),
    re.compile(r"\b(UPDATE)\s+\w+\s+SET\b", re.IGNORECASE),
    re.compile(r"\b(DELETE)\s+FROM\b", re.IGNORECASE),
    re.compile(r"\b(DROP)\s+(TABLE|DATABASE|INDEX|VIEW|SCHEMA)\b", re.IGNORECASE),
    re.compile(r"\b(CREATE)\s+(TABLE|DATABASE|INDEX|VIEW|SCHEMA)\b", re.IGNORECASE),
    re.compile(r"\b(ALTER)\s+(TABLE|DATABASE|INDEX|VIEW|SCHEMA)\b", re.IGNORECASE),
    re.compile(r"\b(TRUNCATE)\s+(TABLE)?\b", re.IGNORECASE),
    re.compile(r"\b(GRANT)\b", re.IGNORECASE),
    re.compile(r"\b(REVOKE)\b", re.IGNORECASE),
    re.compile(r"\b(EXEC(UTE)?)\s+", re.IGNORECASE),
]

# Patterns for dangerous SQL constructs
_INJECTION_PATTERNS = [
    re.compile(r";\s*(DROP|DELETE|INSERT|UPDATE|ALTER|CREATE|TRUNCATE)\b", re.IGNORECASE),
    re.compile(r"--\s*$", re.MULTILINE),  # SQL comment injection at end of line
    re.compile(r"/\*.*\*/", re.DOTALL),   # Block comments (can hide malicious code)
    re.compile(r"\bUNION\s+ALL\s+SELECT\b.*\bFROM\s+information_schema\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bINTO\s+(OUTFILE|DUMPFILE)\b", re.IGNORECASE),
    re.compile(r"\bLOAD\s+DATA\b", re.IGNORECASE),
    re.compile(r"\bLOAD_FILE\s*\(", re.IGNORECASE),
]


class SQLSafetyError(Exception):
    """Raised when SQL fails safety checks."""

    def __init__(self, message: str, sql: str = "", violations: list[str] | None = None) -> None:
        super().__init__(message)
        self.sql = sql
        self.violations = violations or []


def check_read_only(sql: str) -> list[str]:
    """Check that SQL is read-only. Returns list of violations."""
    violations = []
    for pattern in _WRITE_PATTERNS:
        match = pattern.search(sql)
        if match:
            violations.append(f"Write operation detected: {match.group(0).strip()}")
    return violations


def check_injection(sql: str) -> list[str]:
    """Check for potential SQL injection patterns. Returns list of warnings."""
    warnings = []
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(sql):
            warnings.append(f"Suspicious pattern detected: {pattern.pattern[:50]}")
    return warnings


def validate_sql(sql: str, read_only: bool = True) -> None:
    """Validate SQL for safety. Raises SQLSafetyError on violations."""
    violations = []

    if read_only:
        violations.extend(check_read_only(sql))

    injection_warnings = check_injection(sql)
    violations.extend(injection_warnings)

    if violations:
        raise SQLSafetyError(
            f"SQL safety check failed: {'; '.join(violations)}",
            sql=sql,
            violations=violations,
        )


def sanitize_identifier(name: str) -> str:
    """Sanitize a SQL identifier to prevent injection.

    Only allows alphanumeric characters, underscores, and dots.
    """
    if not name:
        raise ValueError("Empty identifier")

    # Remove anything that isn't alphanumeric, underscore, or dot
    sanitized = re.sub(r"[^\w.]", "", name)

    if not sanitized:
        raise ValueError(f"Identifier '{name}' contains no valid characters")

    # Prevent reserved words from being used as unquoted identifiers
    if sanitized.upper() in _RESERVED_WORDS:
        return f'"{sanitized}"'

    return sanitized


# Common SQL reserved words
_RESERVED_WORDS = frozenset({
    "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "INSERT", "UPDATE",
    "DELETE", "DROP", "CREATE", "ALTER", "TABLE", "INDEX", "VIEW", "JOIN",
    "LEFT", "RIGHT", "INNER", "OUTER", "ON", "GROUP", "BY", "ORDER",
    "HAVING", "LIMIT", "OFFSET", "UNION", "ALL", "AS", "IN", "EXISTS",
    "BETWEEN", "LIKE", "IS", "NULL", "TRUE", "FALSE", "CASE", "WHEN",
    "THEN", "ELSE", "END", "DISTINCT", "COUNT", "SUM", "AVG", "MIN",
    "MAX", "INTO", "VALUES",
})
