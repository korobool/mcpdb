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
        assert "clean_cache" in result.stdout

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


class TestCleanCacheCLI:
    def test_clean_cache_stats(self):
        """clean_cache --stats should print stats and exit 0."""
        result = subprocess.run(
            [sys.executable, "-m", "mcpdb", "clean_cache", "--stats"],
            capture_output=True, text=True,
            cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0
        # Should print some kind of stats output
        assert "cache" in result.stdout.lower() or "Memory" in result.stdout

    def test_clean_cache_clears_all(self, tmp_path, monkeypatch):
        """clean_cache (no args) should clear everything."""
        from mcpdb.config import ExperienceConfig
        from mcpdb.experience.service import ExperienceService
        from mcpdb.experience.records import SuccessRecord

        # Set up a service with data in a temp dir
        exp_config = ExperienceConfig(storage_dir=str(tmp_path / "exp"))
        service = ExperienceService(exp_config)
        service.store.store_success(SuccessRecord(
            intent_hash="h1", question="q1", source_fingerprint="fp1",
            schema_hash="sh1", query_mode="simple", steps=[], response="r1",
        ))
        assert len(service.store.list_fingerprints()) == 1

        # Now run clean_cache via the function directly
        from mcpdb.__main__ import _clean_cache
        from mcpdb.config import load_config
        config = load_config()
        # Override experience storage_dir to our tmp dir
        config.experience.storage_dir = str(tmp_path / "exp")

        _clean_cache(config, [])
        # Verify cleared
        service2 = ExperienceService(exp_config)
        assert len(service2.store.list_fingerprints()) == 0

    def test_clean_cache_source(self, tmp_path):
        """clean_cache --source <fp> clears only that source."""
        from mcpdb.config import ExperienceConfig
        from mcpdb.experience.service import ExperienceService
        from mcpdb.experience.records import SuccessRecord

        exp_config = ExperienceConfig(storage_dir=str(tmp_path / "exp"))
        service = ExperienceService(exp_config)
        service.store.store_success(SuccessRecord(
            intent_hash="h1", question="q1", source_fingerprint="fp_a",
            schema_hash="sh", query_mode="simple", steps=[], response="r1",
        ))
        service.store.store_success(SuccessRecord(
            intent_hash="h2", question="q2", source_fingerprint="fp_b",
            schema_hash="sh", query_mode="simple", steps=[], response="r2",
        ))
        assert len(service.store.list_fingerprints()) == 2

        from mcpdb.__main__ import _clean_cache
        from mcpdb.config import load_config
        config = load_config()
        config.experience.storage_dir = str(tmp_path / "exp")

        _clean_cache(config, ["--source", "fp_a"])

        service2 = ExperienceService(exp_config)
        fps = service2.store.list_fingerprints()
        assert "fp_a" not in fps
        assert "fp_b" in fps
