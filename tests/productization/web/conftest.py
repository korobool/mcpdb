"""Playwright fixtures for web client e2e tests."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture(scope="session")
def web_server():
    """Start the mcpdb web server for testing."""
    import subprocess
    import sys

    port = 18765  # Use a non-standard port for testing
    env = os.environ.copy()
    # Ensure MCPDB_DATABASE_URL is set for the server
    if "MCPDB_DATABASE_URL" not in env:
        env["MCPDB_DATABASE_URL"] = "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins"

    proc = subprocess.Popen(
        [sys.executable, "-m", "mcpdb", "web", "--port", str(port), "--no-browser"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to start
    import urllib.request
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://localhost:{port}/", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    else:
        proc.kill()
        raise RuntimeError("Web server failed to start")

    yield f"http://localhost:{port}"

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def screenshot_dir():
    """Directory for storing test screenshots."""
    d = Path(__file__).parent / "screenshots"
    d.mkdir(exist_ok=True)
    return d
