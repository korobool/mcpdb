"""Tests for v3.9.x — CLI entry points."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from mcpdb import __version__


class TestCLI:
    def test_version_print(self):
        result = subprocess.run(
            [sys.executable, "-m", "mcpdb"],
            capture_output=True, text=True,
            cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0
        assert f"mcpdb v{__version__}" in result.stdout

    def test_version_flag(self):
        result = subprocess.run(
            [sys.executable, "-m", "mcpdb", "--version"],
            capture_output=True, text=True,
            cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0
        assert __version__ in result.stdout

    def test_help_flag(self):
        result = subprocess.run(
            [sys.executable, "-m", "mcpdb", "--help"],
            capture_output=True, text=True,
            cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0
        assert "Usage:" in result.stdout
        assert "serve" in result.stdout
        assert "web" in result.stdout
        assert "query" in result.stdout

    def test_unknown_command(self):
        result = subprocess.run(
            [sys.executable, "-m", "mcpdb", "foobar"],
            capture_output=True, text=True,
            cwd=Path(__file__).parent.parent,
        )
        assert result.returncode != 0
        assert "Unknown command" in result.stdout

    def test_query_no_args(self):
        result = subprocess.run(
            [sys.executable, "-m", "mcpdb", "query"],
            capture_output=True, text=True,
            cwd=Path(__file__).parent.parent,
        )
        assert result.returncode != 0
        assert "Usage:" in result.stdout
