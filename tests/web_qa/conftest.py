"""Playwright fixtures for web QA testing.

Usage:
    # Headless (CI mode):
    pytest tests/web_qa/

    # Visual mode (watch in browser with slowmo):
    pytest tests/web_qa/ --headed --slowmo 300

    # Visual mode shortcut:
    pytest tests/web_qa/ --visible

    # Record video:
    pytest tests/web_qa/ --video on

    # Specific browser:
    pytest tests/web_qa/ --browser firefox
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


def pytest_addoption(parser):
    """Add custom CLI options for web QA tests."""
    parser.addoption(
        "--visible",
        action="store_true",
        default=False,
        help="Shortcut for --headed --slowmo 300 (watch tests in browser)",
    )
    parser.addoption(
        "--record-video",
        action="store_true",
        default=False,
        help="Record video of browser sessions (saves to artifacts/videos)",
    )


def pytest_configure(config):
    """Handle --visible shortcut: set --headed and default slowmo."""
    if config.getoption("--visible", default=False):
        # Set headed mode
        config.option.headed = True
        # Set slowmo only if not explicitly provided
        if config.getoption("--slowmo", default=0) == 0:
            config.option.slowmo = 300
    # Register slow marker
    config.addinivalue_line("markers", "slow: mark test as slow (extended/deep mode)")


# ── Port for test server ──────────────────────────────────────────────

TEST_PORT = 18769


# ── Browser launch options ────────────────────────────────────────────

@pytest.fixture(scope="session")
def browser_type_launch_args():
    """Allow popups (needed for HTML export opening in new tab)."""
    return {"args": ["--disable-popup-blocking"]}


# ── Browser context options ───────────────────────────────────────────

@pytest.fixture(scope="session")
def browser_context_args(request, tmp_path_factory):
    """Configure browser context: viewport, video."""
    args = {
        "viewport": {"width": 1920, "height": 1080},
        "ignore_https_errors": True,
    }
    if request.config.getoption("--record-video", default=False):
        video_dir = Path(__file__).parent / "artifacts" / "videos"
        video_dir.mkdir(parents=True, exist_ok=True)
        args["record_video_dir"] = str(video_dir)
        args["record_video_size"] = {"width": 1920, "height": 1080}
    return args


# ── Web server fixture ────────────────────────────────────────────────

@pytest.fixture(scope="session")
def web_server():
    """Start mcpdb web server for testing."""
    env = os.environ.copy()
    if "MCPDB_DATABASE_URL" not in env:
        env["MCPDB_DATABASE_URL"] = "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins"

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "mcpdb", "web",
            "--port", str(TEST_PORT),
            "--no-browser",
            "--no-cache",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to start
    import urllib.request
    url = f"http://localhost:{TEST_PORT}/"
    for _ in range(30):
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    else:
        proc.kill()
        stdout = proc.stdout.read().decode() if proc.stdout else ""
        stderr = proc.stderr.read().decode() if proc.stderr else ""
        raise RuntimeError(
            f"Web server failed to start on port {TEST_PORT}\n"
            f"stdout: {stdout[:500]}\nstderr: {stderr[:500]}"
        )

    yield url

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


# ── Screenshot & artifact directory ───────────────────────────────────

@pytest.fixture(scope="session")
def artifact_dir():
    """Directory for screenshots, DOM dumps, traces."""
    d = Path(__file__).parent / "artifacts"
    d.mkdir(exist_ok=True)
    (d / "screenshots").mkdir(exist_ok=True)
    (d / "dom").mkdir(exist_ok=True)
    (d / "traces").mkdir(exist_ok=True)
    return d


# ── Auto-capture on failure ──────────────────────────────────────────

@pytest.fixture(autouse=True)
def capture_on_failure(request, page, artifact_dir):
    """Capture screenshot + DOM + console logs on test failure."""
    console_messages = []

    def _on_console(msg):
        console_messages.append({
            "type": msg.type,
            "text": msg.text,
        })

    page.on("console", _on_console)

    yield

    if hasattr(request.node, "rep_call") and request.node.rep_call.failed:
        test_name = request.node.name.replace("/", "_").replace("::", "_")

        # Screenshot
        try:
            page.screenshot(
                path=str(artifact_dir / "screenshots" / f"FAIL_{test_name}.png"),
                full_page=True,
            )
        except Exception:
            pass

        # DOM snapshot
        try:
            html = page.content()
            (artifact_dir / "dom" / f"FAIL_{test_name}.html").write_text(html)
        except Exception:
            pass

        # Console logs
        try:
            (artifact_dir / "traces" / f"FAIL_{test_name}_console.json").write_text(
                json.dumps(console_messages, indent=2)
            )
        except Exception:
            pass


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Store test result for capture_on_failure fixture."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)
