"""Tests for v0.0.1 — project bootstrap."""

import subprocess
import sys
from pathlib import Path

from mcpdb import __version__
from mcpdb.config import McpdbConfig, load_config


def test_version_exists():
    assert __version__ == "4.0.0"


def test_python_m_mcpdb_prints_version():
    result = subprocess.run(
        [sys.executable, "-m", "mcpdb"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0
    assert f"mcpdb v{__version__}" in result.stdout


def test_load_config_defaults():
    config = McpdbConfig()
    assert config.llm.reasoning.provider == "gemini"
    assert config.llm.reasoning.model == "gemini-2.5-pro"
    assert config.llm.fast.model == "gemini-2.5-flash"
    assert config.llm.temperature == 0.0
    assert config.server.transport == "stdio"
    assert config.server.port == 8765
    assert config.execution.query_timeout == 30
    assert config.execution.read_only is True
    assert config.cost_gate.large_table_threshold == 1_000_000
    assert config.duckdb.memory_limit == "2GB"
    assert config.experience.enabled is True
    assert config.ui.theme == "dark"


def test_load_config_from_yaml(tmp_path):
    yaml_file = tmp_path / "mcpdb.yaml"
    yaml_file.write_text("""\
llm:
  reasoning:
    provider: openai
    model: gpt-4o
  temperature: 0.5
server:
  transport: sse
  port: 9999
execution:
  query_timeout: 60
  read_only: false
""")
    config = load_config(yaml_file)
    assert config.llm.reasoning.provider == "openai"
    assert config.llm.reasoning.model == "gpt-4o"
    assert config.llm.temperature == 0.5
    # fast model keeps default since not specified
    assert config.llm.fast.model == "gemini-2.5-flash"
    assert config.server.transport == "sse"
    assert config.server.port == 9999
    assert config.execution.query_timeout == 60
    assert config.execution.read_only is False


def test_load_config_env_var_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "sk-test-123")
    yaml_file = tmp_path / "mcpdb.yaml"
    yaml_file.write_text("""\
llm:
  reasoning:
    api_key: ${MY_API_KEY}
""")
    config = load_config(yaml_file)
    assert config.llm.reasoning.api_key == "sk-test-123"


def test_load_config_missing_file():
    config = load_config("/nonexistent/path/mcpdb.yaml")
    # Falls back to defaults
    assert config.llm.reasoning.provider == "gemini"


def test_load_config_empty_file(tmp_path):
    yaml_file = tmp_path / "mcpdb.yaml"
    yaml_file.write_text("")
    config = load_config(yaml_file)
    assert config.llm.reasoning.provider == "gemini"
