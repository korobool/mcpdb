"""Logging setup for MCPDB."""

from __future__ import annotations

import logging
import os
import sys


def setup_logging(level: str | None = None) -> logging.Logger:
    """Configure and return the root mcpdb logger.

    Level resolution order:
    1. Explicit level argument
    2. MCPDB_LOG_LEVEL environment variable
    3. INFO default
    """
    if level is None:
        level = os.environ.get("MCPDB_LOG_LEVEL", "INFO")

    log_level = getattr(logging, level.upper(), logging.INFO)

    logger = logging.getLogger("mcpdb")
    logger.setLevel(log_level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(log_level)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
