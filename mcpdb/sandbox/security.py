"""Security checks for Python sandbox — import validation and resource limits."""

from __future__ import annotations

import ast
import platform

ALLOWED_MODULES = frozenset({
    # Data processing
    "pandas", "numpy",
    # Visualization
    "matplotlib", "matplotlib.pyplot", "seaborn",
    # Standard library (safe subset)
    "json", "re", "math", "datetime", "collections", "itertools",
    "functools", "operator", "decimal", "fractions", "statistics",
    "string", "textwrap", "copy", "pprint",
})

BLOCKED_MODULES = frozenset({
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


def validate_imports(code: str) -> list[str]:
    """Check code for disallowed imports. Returns list of violations."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []  # Let the executor handle syntax errors

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _check_module(alias.name, violations)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                _check_module(node.module, violations)

    return violations


def _check_module(module_name: str, violations: list[str]) -> None:
    """Check if a module is allowed."""
    # Get the top-level module
    top_level = module_name.split(".")[0]

    # Explicit block list
    if top_level in BLOCKED_MODULES or module_name in BLOCKED_MODULES:
        violations.append(f"Import of '{module_name}' is not allowed")
        return

    # Check if it's in the allow list (by top-level or full name)
    if top_level not in _allowed_top_levels() and module_name not in ALLOWED_MODULES:
        violations.append(f"Import of '{module_name}' is not allowed")


def _allowed_top_levels() -> frozenset[str]:
    """Get set of allowed top-level module names."""
    return frozenset(m.split(".")[0] for m in ALLOWED_MODULES)


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

    # Memory limit (generous to allow numpy/pandas)
    mem_bytes = memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))

    # CPU time limit
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
