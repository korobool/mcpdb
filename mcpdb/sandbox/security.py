"""Security checks for Python sandbox — import validation and resource limits."""

from __future__ import annotations

import ast
import platform
from typing import Sequence

# --- Default module lists ---

DEFAULT_ALLOWED_MODULES: frozenset[str] = frozenset({
    # Data processing
    "pandas", "numpy", "polars", "pyarrow",
    # Scientific computing
    "scipy", "scipy.stats", "scipy.optimize", "scipy.signal", "scipy.spatial",
    "scipy.interpolate", "scipy.integrate", "scipy.linalg",
    # Machine learning
    "sklearn", "scikit-learn",
    "torch", "torch.nn", "torch.optim", "torch.utils",
    "xgboost", "lightgbm", "catboost",
    # Visualization
    "matplotlib", "matplotlib.pyplot", "seaborn", "plotly", "plotly.express",
    "plotly.graph_objects",
    # NLP / text
    "nltk", "spacy", "transformers",
    # Tabular / data wrangling
    "sqlalchemy",
    "duckdb",
    "openpyxl",
    "xlsxwriter",
    # Geospatial
    "shapely", "geopandas",
    # Image
    "PIL", "pillow",
    # Standard library (safe subset)
    "json", "re", "math", "datetime", "collections", "itertools",
    "functools", "operator", "decimal", "fractions", "statistics",
    "string", "textwrap", "copy", "pprint", "dataclasses", "enum",
    "typing", "abc", "bisect", "heapq", "array", "struct",
    "csv", "io", "base64", "hashlib", "hmac",
    "random", "secrets",
    "time", "calendar", "zoneinfo",
    "contextlib", "warnings",
    "numbers", "cmath",
    "difflib", "unicodedata",
})

DEFAULT_BLOCKED_MODULES: frozenset[str] = frozenset({
    "os", "sys", "subprocess", "shutil", "pathlib",
    "socket", "http", "urllib", "requests", "httpx",
    "importlib", "ctypes", "signal", "threading", "multiprocessing",
    "pickle", "shelve", "marshal",
    "code", "codeop", "compile", "compileall",
    "webbrowser", "antigravity",
    "builtins", "__builtin__",
})


class ImportViolation(Exception):
    """Raised when code tries to import a disallowed module."""
    pass


class SandboxSecurity:
    """Configurable import validator with allow/block lists.

    Modes:
    - Normal (default): imports checked against allowed + blocked lists.
    - allow_all=True: all imports allowed, blocked list still enforced.
    - allow_all=True + empty blocked: everything allowed (security off).
    """

    def __init__(
        self,
        allowed: frozenset[str] | None = None,
        blocked: frozenset[str] | None = None,
        allow_all: bool = False,
    ) -> None:
        self.allowed = allowed if allowed is not None else DEFAULT_ALLOWED_MODULES
        self.blocked = blocked if blocked is not None else DEFAULT_BLOCKED_MODULES
        self.allow_all = allow_all
        self._allowed_top: frozenset[str] = frozenset(
            m.split(".")[0] for m in self.allowed
        )

    def validate_imports(self, code: str) -> list[str]:
        """Check code for disallowed imports. Returns list of violations."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []  # Let the executor handle syntax errors

        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._check_module(alias.name, violations)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self._check_module(node.module, violations)

        return violations

    def _check_module(self, module_name: str, violations: list[str]) -> None:
        """Check if a module is allowed."""
        top_level = module_name.split(".")[0]

        # Explicit block list always enforced (unless empty)
        if top_level in self.blocked or module_name in self.blocked:
            violations.append(f"Import of '{module_name}' is not allowed")
            return

        # In allow_all mode, anything not blocked is fine
        if self.allow_all:
            return

        # Normal mode: must be in the allow list
        if top_level not in self._allowed_top and module_name not in self.allowed:
            violations.append(f"Import of '{module_name}' is not allowed")

    def get_allowed_for_prompt(self) -> str:
        """Return a concise summary of allowed libraries for LLM prompts."""
        if self.allow_all:
            return "Any Python library is available (no import restrictions)."

        # Group by category for readability
        categories = {
            "data": ["pandas", "numpy", "polars", "pyarrow", "duckdb"],
            "ml": ["sklearn", "torch", "xgboost", "lightgbm", "scipy"],
            "viz": ["matplotlib", "seaborn", "plotly"],
            "stdlib": ["json", "re", "math", "datetime", "collections",
                       "itertools", "statistics", "csv", "io", "random"],
        }
        parts = []
        for cat, modules in categories.items():
            available = [m for m in modules if m in self.allowed or m in self._allowed_top]
            if available:
                parts.append(", ".join(available))
        return "; ".join(parts) if parts else "pandas, numpy"


# --- Module-level convenience functions (backward-compatible) ---

_default_security = SandboxSecurity()


def validate_imports(code: str) -> list[str]:
    """Check code for disallowed imports using default security settings."""
    return _default_security.validate_imports(code)


def configure_security(
    allowed: Sequence[str] | None = None,
    blocked: Sequence[str] | None = None,
    allow_all: bool = False,
) -> SandboxSecurity:
    """Create and set a new global security configuration.

    Returns the new SandboxSecurity instance.
    """
    global _default_security
    _default_security = SandboxSecurity(
        allowed=frozenset(allowed) if allowed is not None else None,
        blocked=frozenset(blocked) if blocked is not None else None,
        allow_all=allow_all,
    )
    return _default_security


def get_security() -> SandboxSecurity:
    """Return the current global SandboxSecurity instance."""
    return _default_security


# Keep old names exported for backward compat
ALLOWED_MODULES = DEFAULT_ALLOWED_MODULES
BLOCKED_MODULES = DEFAULT_BLOCKED_MODULES


def get_resource_limits(
    memory_mb: int = 512,
    cpu_seconds: int = 30,
) -> dict[str, int]:
    """Return resource limit settings for the sandbox subprocess.

    Only applies on Linux (resource module uses RLIMIT_* constants).
    """
    if platform.system() != "Linux":
        return {}

    return {
        "memory_bytes": memory_mb * 1024 * 1024,
        "cpu_seconds": cpu_seconds,
    }


def apply_resource_limits(memory_mb: int = 2048, cpu_seconds: int = 30) -> None:
    """Apply resource limits to the current process. Called inside subprocess."""
    if platform.system() != "Linux":
        return

    import resource

    # Memory limit (generous to allow numpy/pandas/torch)
    mem_bytes = memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))

    # CPU time limit
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
