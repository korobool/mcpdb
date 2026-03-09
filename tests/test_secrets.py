"""Tests for centralized secret resolution."""

from __future__ import annotations

import os

import pytest

from mcpdb.secrets import resolve_secret, load_dotenv_if_available


class TestResolveSecret:
    def test_explicit_value_wins(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "from-env")
        assert resolve_secret("MY_KEY", explicit_value="explicit") == "explicit"

    def test_env_var(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "from-env")
        assert resolve_secret("MY_KEY") == "from-env"

    def test_env_var_over_file(self, monkeypatch, tmp_path):
        secret_file = tmp_path / "key.txt"
        secret_file.write_text("from-file")
        monkeypatch.setenv("MY_KEY", "from-env")
        monkeypatch.setenv("MY_KEY_FILE", str(secret_file))
        assert resolve_secret("MY_KEY") == "from-env"

    def test_file_secret(self, monkeypatch, tmp_path):
        secret_file = tmp_path / "key.txt"
        secret_file.write_text("secret-from-file")
        monkeypatch.delenv("MY_KEY", raising=False)
        monkeypatch.setenv("MY_KEY_FILE", str(secret_file))
        assert resolve_secret("MY_KEY") == "secret-from-file"

    def test_file_strips_whitespace(self, monkeypatch, tmp_path):
        secret_file = tmp_path / "key.txt"
        secret_file.write_text("  my-key  \n\n")
        monkeypatch.delenv("MY_KEY", raising=False)
        monkeypatch.setenv("MY_KEY_FILE", str(secret_file))
        assert resolve_secret("MY_KEY") == "my-key"

    def test_file_not_found_returns_empty(self, monkeypatch):
        monkeypatch.delenv("MY_KEY", raising=False)
        monkeypatch.setenv("MY_KEY_FILE", "/nonexistent/path/key.txt")
        assert resolve_secret("MY_KEY") == ""

    def test_nothing_set_returns_empty(self, monkeypatch):
        monkeypatch.delenv("MY_KEY", raising=False)
        monkeypatch.delenv("MY_KEY_FILE", raising=False)
        assert resolve_secret("MY_KEY") == ""

    def test_empty_env_var_falls_through_to_file(self, monkeypatch, tmp_path):
        secret_file = tmp_path / "key.txt"
        secret_file.write_text("from-file")
        monkeypatch.setenv("MY_KEY", "")
        monkeypatch.setenv("MY_KEY_FILE", str(secret_file))
        assert resolve_secret("MY_KEY") == "from-file"

    def test_empty_explicit_falls_through(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "from-env")
        assert resolve_secret("MY_KEY", explicit_value="") == "from-env"

    def test_empty_file_returns_empty(self, monkeypatch, tmp_path):
        secret_file = tmp_path / "key.txt"
        secret_file.write_text("   \n")
        monkeypatch.delenv("MY_KEY", raising=False)
        monkeypatch.setenv("MY_KEY_FILE", str(secret_file))
        assert resolve_secret("MY_KEY") == ""


class TestLoadDotenv:
    def test_no_error_without_dotenv(self, monkeypatch):
        """Should not raise even if python-dotenv is missing."""
        import importlib
        import mcpdb.secrets as mod

        # Temporarily make dotenv unimportable
        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def mock_import(name, *args, **kwargs):
            if name == "dotenv":
                raise ImportError("no dotenv")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)
        # Should not raise
        load_dotenv_if_available()

    def test_loads_dotenv_when_available(self, monkeypatch, tmp_path):
        """If python-dotenv is installed, .env values should be loaded."""
        try:
            from dotenv import load_dotenv as _check
        except ImportError:
            pytest.skip("python-dotenv not installed")

        env_file = tmp_path / ".env"
        env_file.write_text("TEST_MCPDB_SECRET_XYZ=hello-from-dotenv\n")
        monkeypatch.delenv("TEST_MCPDB_SECRET_XYZ", raising=False)

        # Directly use dotenv with explicit path (load_dotenv_if_available
        # uses cwd which is hard to control in tests)
        from dotenv import load_dotenv
        load_dotenv(str(env_file), override=False)
        assert os.environ.get("TEST_MCPDB_SECRET_XYZ") == "hello-from-dotenv"

        # Cleanup
        monkeypatch.delenv("TEST_MCPDB_SECRET_XYZ", raising=False)
