"""Dialect factory and registry."""

from __future__ import annotations

from mcpdb.sources.database.dialects.base import DatabaseDialect, ExplainResult


_DIALECT_MAP: dict[str, type[DatabaseDialect]] = {}


def _register_builtins() -> None:
    """Lazily register all built-in dialects."""
    if _DIALECT_MAP:
        return

    from mcpdb.sources.database.dialects.postgresql import PostgreSQLDialect
    from mcpdb.sources.database.dialects.mysql import MySQLDialect
    from mcpdb.sources.database.dialects.sqlite import SQLiteDialect
    from mcpdb.sources.database.dialects.mssql import MSSQLDialect
    from mcpdb.sources.database.dialects.oracle import OracleDialect

    for cls in [PostgreSQLDialect, MySQLDialect, SQLiteDialect, MSSQLDialect, OracleDialect]:
        for name in cls.names:
            _DIALECT_MAP[name] = cls


def create_dialect(url: str) -> DatabaseDialect:
    """Create a dialect instance from a connection URL or dialect name.

    Accepts:
      - Full URL: "postgresql://user:pass@host/db"
      - Dialect name: "postgresql", "mysql", "sqlite", etc.
    """
    _register_builtins()

    # Extract dialect from URL scheme
    scheme = url.split("://")[0] if "://" in url else url
    # Handle driver suffixes like "postgresql+psycopg2"
    dialect_name = scheme.split("+")[0].lower()

    cls = _DIALECT_MAP.get(dialect_name)
    if cls is None:
        available = sorted(set(c.__name__ for c in _DIALECT_MAP.values()))
        raise ValueError(
            f"Unknown dialect '{dialect_name}'. Available: {available}"
        )
    return cls()


__all__ = ["DatabaseDialect", "ExplainResult", "create_dialect"]
