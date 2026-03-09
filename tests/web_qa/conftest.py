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
def browser_type_launch_args(request):
    """Allow popups; start maximized when headed."""
    args = ["--disable-popup-blocking"]
    if request.config.getoption("--headed", default=False):
        args.append("--start-maximized")
    return {"args": args}


# ── Browser context options ───────────────────────────────────────────

@pytest.fixture(scope="session")
def browser_context_args(request, tmp_path_factory):
    """Configure browser context: viewport, video, zoom."""
    # Large viewport for headed mode so more content fits on screen
    headed = request.config.getoption("--headed", default=False)
    if headed:
        args = {
            "viewport": {"width": 2560, "height": 1440},
            "ignore_https_errors": True,
            "device_scale_factor": 0.75,  # zoom out — more fits on screen
        }
    else:
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

class _WebServerManager:
    """Manages the mcpdb web server, auto-restarting on crash."""

    def __init__(self):
        self.proc = None
        self.log_file = None
        self.url = f"http://localhost:{TEST_PORT}/"
        self.env = os.environ.copy()
        if "MCPDB_DATABASE_URL" not in self.env:
            self.env["MCPDB_DATABASE_URL"] = "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins"
        self.log_dir = Path(__file__).parent / "artifacts"
        self.log_dir.mkdir(exist_ok=True)

    def start(self):
        """Start or restart the server."""
        self.stop()
        self.log_file = open(self.log_dir / "server.log", "a")
        self.proc = subprocess.Popen(
            [
                sys.executable, "-m", "mcpdb", "web",
                "--port", str(TEST_PORT),
                "--no-browser",
                "--no-cache",
            ],
            env=self.env,
            stdout=self.log_file,
            stderr=subprocess.STDOUT,
        )
        import urllib.request
        for _ in range(30):
            try:
                urllib.request.urlopen(self.url, timeout=1)
                return
            except Exception:
                time.sleep(0.5)
        raise RuntimeError(f"Web server failed to start on port {TEST_PORT}")

    def ensure_running(self):
        """Check if server is alive and restart if needed."""
        if self.proc is None or self.proc.poll() is not None:
            print(f"\n  [SERVER] Restarting web server (was dead)...")
            self.start()
            return True
        # Also check HTTP health
        import urllib.request
        try:
            urllib.request.urlopen(self.url, timeout=2)
        except Exception:
            print(f"\n  [SERVER] Server unresponsive, restarting...")
            self.start()
            return True
        return False

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        if self.log_file:
            self.log_file.close()
            self.log_file = None


@pytest.fixture(scope="session")
def _server_manager():
    mgr = _WebServerManager()
    mgr.start()
    yield mgr
    mgr.stop()


@pytest.fixture(scope="session")
def web_server(_server_manager):
    """URL of the test web server (auto-restarts on crash)."""
    return _server_manager.url


@pytest.fixture(autouse=True)
def _ensure_server(_server_manager):
    """Before each test, ensure the web server is alive."""
    _server_manager.ensure_running()


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
