"""Configuration loading for MCPDB."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class LLMModelConfig:
    provider: str = "gemini"
    model: str = "gemini-2.5-pro"
    api_key: str = ""


@dataclass
class LLMConfig:
    reasoning: LLMModelConfig = field(default_factory=LLMModelConfig)
    fast: LLMModelConfig = field(default_factory=lambda: LLMModelConfig(model="gemini-2.5-flash"))
    temperature: float = 0.0
    timeout: int = 120
    budget_per_question_usd: float = 2.00


@dataclass
class ServerConfig:
    transport: str = "stdio"
    host: str = "localhost"
    port: int = 8765


@dataclass
class ExecutionConfig:
    query_timeout: int = 30
    python_timeout: int = 60
    max_rows_display: int = 100
    read_only: bool = True


@dataclass
class CostGateConfig:
    enabled: bool = True
    auto_mode: bool = False
    large_table_threshold: int = 1_000_000


@dataclass
class DuckDBConfig:
    memory_limit: str = "2GB"
    threads: int = 4


@dataclass
class ExperienceConfig:
    enabled: bool = True
    storage_dir: str = "~/.mcpdb/experience"
    embedding_provider: str = "auto"
    max_success_records: int = 2000
    max_failure_records: int = 500
    max_strategy_records: int = 200
    cache_max_age_days: int = 30
    template_max_age_days: int = 90
    anti_pattern_min_occurrences: int = 2
    cross_dialect_promotion_threshold: int = 2
    similarity_threshold_high: float = 0.85
    similarity_threshold_medium: float = 0.65
    quality_eval_enabled: bool = True
    quality_eval_min_score: int = 7
    quality_eval_poll_interval: float = 30.0
    quality_eval_max_retries: int = 3


@dataclass
class UIConfig:
    theme: str = "dark"
    port: int = 8080


@dataclass
class SandboxConfig:
    """Python sandbox security configuration.

    allowed_modules: Extra modules to allow (added to built-in defaults).
    blocked_modules: Extra modules to block (added to built-in defaults).
    allow_all: If True, all imports are allowed except explicitly blocked ones.
                Set both allow_all=True and blocked_modules=[] to disable security entirely.
    memory_mb: Memory limit for sandbox subprocess.
    cpu_seconds: CPU time limit for sandbox subprocess.
    """
    allowed_modules: list[str] = field(default_factory=list)
    blocked_modules: list[str] = field(default_factory=list)
    allow_all: bool = False
    memory_mb: int = 2048
    cpu_seconds: int = 60


@dataclass
class McpdbConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    cost_gate: CostGateConfig = field(default_factory=CostGateConfig)
    duckdb: DuckDBConfig = field(default_factory=DuckDBConfig)
    experience: ExperienceConfig = field(default_factory=ExperienceConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)


def _resolve_env_vars(value: str) -> str:
    """Resolve ${VAR_NAME} patterns in string values."""
    if not isinstance(value, str):
        return value
    import re
    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, "")
    return re.sub(r"\$\{(\w+)\}", _replace, value)


def _resolve_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Recursively resolve env vars in a dict."""
    result = {}
    for k, v in d.items():
        if isinstance(v, dict):
            result[k] = _resolve_dict(v)
        elif isinstance(v, str):
            result[k] = _resolve_env_vars(v)
        else:
            result[k] = v
    return result


def _build_dataclass(cls: type, data: dict[str, Any]) -> Any:
    """Recursively build a dataclass from a dict, ignoring unknown keys."""
    import dataclasses
    if not dataclasses.is_dataclass(cls):
        return data

    field_types = {f.name: f.type for f in dataclasses.fields(cls)}
    kwargs = {}
    for fname, ftype in field_types.items():
        if fname not in data:
            continue
        val = data[fname]
        # Resolve the actual type from string annotations
        if isinstance(ftype, str):
            ftype = eval(ftype, {**globals(), **{cls.__name__: cls for cls in [
                LLMModelConfig, LLMConfig, ServerConfig, ExecutionConfig,
                CostGateConfig, DuckDBConfig, ExperienceConfig, UIConfig, SandboxConfig, McpdbConfig,
            ]}})
        if dataclasses.is_dataclass(ftype) and isinstance(val, dict):
            kwargs[fname] = _build_dataclass(ftype, val)
        else:
            kwargs[fname] = val
    return cls(**kwargs)


def load_config(path: str | Path | None = None) -> McpdbConfig:
    """Load configuration from YAML file with env var resolution.

    Search order:
    1. Explicit path argument
    2. MCPDB_CONFIG environment variable
    3. ./mcpdb.yaml in current directory
    4. Defaults (no file needed)
    """
    if path is None:
        path = os.environ.get("MCPDB_CONFIG")

    if path is None:
        default_path = Path("mcpdb.yaml")
        if default_path.exists():
            path = default_path

    if path is None:
        return McpdbConfig()

    path = Path(path)
    if not path.exists():
        return McpdbConfig()

    with open(path) as f:
        raw = yaml.safe_load(f)

    if not raw or not isinstance(raw, dict):
        return McpdbConfig()

    resolved = _resolve_dict(raw)
    return _build_dataclass(McpdbConfig, resolved)
