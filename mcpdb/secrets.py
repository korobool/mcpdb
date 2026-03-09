"""Centralized secret/API key resolution.

Supports three resolution methods (in priority order):
1. Explicit value passed directly
2. Environment variable: GEMINI_API_KEY=xxx
3. File-based secret: GEMINI_API_KEY_FILE=/run/secrets/gemini_key
   (Docker/Kubernetes convention — reads key from file)

A .env file in the working directory is loaded at startup if
python-dotenv is installed (values don't override real env vars).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("mcpdb.secrets")


def resolve_secret(env_var: str, explicit_value: str = "") -> str:
    """Resolve a secret value from multiple sources.

    Priority: explicit_value > env var > env var _FILE (read from file).
    Returns empty string if nothing is found (never raises).
    """
    # 1. Explicit value wins
    if explicit_value:
        return explicit_value

    # 2. Direct environment variable
    value = os.environ.get(env_var, "")
    if value:
        return value

    # 3. _FILE suffix — read secret from file path
    file_var = f"{env_var}_FILE"
    file_path = os.environ.get(file_var, "")
    if file_path:
        try:
            with open(file_path, encoding="utf-8") as f:
                value = f.read().strip()
            if value:
                logger.debug("Resolved %s from file %s", env_var, file_path)
                return value
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Cannot read %s=%s: %s", file_var, file_path, e)

    return ""


def load_dotenv_if_available() -> None:
    """Load .env file into os.environ if python-dotenv is installed.

    Uses override=False so real env vars always take priority.
    Silently does nothing if python-dotenv is not installed.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except ImportError:
        pass
