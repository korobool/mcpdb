"""Reusable helpers for web QA tests.

Provides high-level actions that map to user interactions:
- connect_database(): add a DB source via the sidebar
- submit_query(): type a question and wait for result
- wait_for_ws_event(): wait for a specific WebSocket event
- get_monitor_state(): read the current monitor panel state
- get_chat_messages(): extract rendered chat messages
- take_screenshot(): capture a named screenshot
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, expect


# ── Source management ─────────────────────────────────────────────────

def connect_database(page: Page, conn_str: str, display_name: str = "", timeout: float = 30_000):
    """Connect a database source via the sidebar UI."""
    # Open the "Add database" details
    details = page.locator("#connect-details")
    if not details.get_attribute("open"):
        details.locator("summary").click()

    # Fill connection string
    conn_input = page.locator("#conn-str")
    conn_input.fill(conn_str)

    if display_name:
        page.locator("#conn-name").fill(display_name)

    # Click Connect
    page.locator("#connect-details .btn-primary").click()

    # Wait for source card to appear in sources list
    page.locator("#sources-list .source-card").first.wait_for(state="visible", timeout=timeout)


def remove_all_sources(page: Page):
    """Remove all connected sources."""
    while True:
        cards = page.locator("#sources-list .source-card")
        if cards.count() == 0:
            break
        # Handle the confirm dialog
        page.on("dialog", lambda d: d.accept())
        cards.first.locator(".remove-btn").click()
        page.wait_for_timeout(500)


def get_source_count(page: Page) -> int:
    """Get the number of connected sources."""
    return page.locator("#sources-list .source-card").count()


def get_source_names(page: Page) -> list[str]:
    """Get display names of all connected sources."""
    cards = page.locator("#sources-list .source-card .name")
    return [cards.nth(i).text_content() for i in range(cards.count())]


# ── Query submission ──────────────────────────────────────────────────

def submit_query(
    page: Page,
    question: str,
    mode: str = "auto",
    timeout: float = 120_000,
    wait_for_result: bool = True,
) -> dict[str, Any] | None:
    """Submit a question and optionally wait for the result.

    Returns the result metadata dict if wait_for_result=True:
        {response, mode, elapsed, has_charts, followup_count, error}
    """
    # Set mode
    if mode != "auto":
        page.locator("#mode-select").select_option(mode)

    # Type the question
    textarea = page.locator("#question")
    textarea.fill(question)

    # Click Send
    page.locator("#send-btn").click()

    if not wait_for_result:
        return None

    return wait_for_query_result(page, timeout)


def wait_for_query_result(page: Page, timeout: float = 120_000) -> dict[str, Any]:
    """Wait for the current query to complete and return result metadata."""
    # Wait for the Send button to reappear (means query is done)
    page.locator("#send-btn").wait_for(state="visible", timeout=timeout)

    # Extract result from the last assistant message
    messages = page.locator(".message.assistant")
    last_msg = messages.last

    result = {
        "response": "",
        "mode": "",
        "elapsed": 0.0,
        "has_charts": False,
        "followup_count": 0,
        "error": False,
    }

    # Get response text
    bubble = last_msg.locator(".bubble")
    if bubble.count() > 0:
        result["response"] = bubble.first.inner_text()

    # Check for error
    if "Error:" in result["response"]:
        result["error"] = True

    # Get metadata (mode + time)
    meta = last_msg.locator(".msg-meta")
    if meta.count() > 0:
        meta_text = meta.first.inner_text()
        if "Mode:" in meta_text:
            result["mode"] = meta_text.split("Mode:")[1].split("·")[0].strip()
        if "Time:" in meta_text:
            time_str = meta_text.split("Time:")[1].strip().rstrip("s")
            try:
                result["elapsed"] = float(time_str)
            except ValueError:
                pass

    # Check for charts
    charts = last_msg.locator(".chart-artifact img")
    result["has_charts"] = charts.count() > 0

    # Count followups
    followups = last_msg.locator(".followup-btn")
    result["followup_count"] = followups.count()

    return result


# ── Monitor panel inspection ─────────────────────────────────────────

def get_monitor_state(page: Page) -> dict[str, Any]:
    """Read the current execution monitor state via JS evaluation.

    Note: JS variables like `mon`, `isQuerying` are script-level (not window.*),
    but they are accessible via evaluate() in the same execution context.
    """
    return page.evaluate("""() => {
        try {
            return {
                phase: typeof mon !== 'undefined' ? mon.phase : 'unknown',
                mode: typeof mon !== 'undefined' ? mon.mode : '',
                stepCount: typeof mon !== 'undefined' ? mon.steps.length : 0,
                logCount: typeof mon !== 'undefined' ? mon.log.length : 0,
                deepInvestigationCount: typeof mon !== 'undefined' ? mon.deepInvestigations.length : 0,
                planStepCount: typeof mon !== 'undefined' ? mon.planStepCount : 0,
                debugAttempts: typeof mon !== 'undefined' ? mon.debugAttempts : 0,
                replanCount: typeof mon !== 'undefined' ? mon.replanCount : 0,
                validationStatus: typeof mon !== 'undefined' ? mon.validationStatus : '',
                elapsed: typeof mon !== 'undefined' ? mon.elapsed : 0,
                isQuerying: typeof isQuerying !== 'undefined' ? isQuerying : false,
            };
        } catch(e) {
            return { phase: 'error', mode: '', stepCount: 0, logCount: 0,
                     deepInvestigationCount: 0, planStepCount: 0,
                     debugAttempts: 0, replanCount: 0, validationStatus: '',
                     elapsed: 0, isQuerying: false };
        }
    }""")


def get_monitor_log(page: Page) -> list[str]:
    """Get the activity log entries from the monitor."""
    return page.evaluate("""() => {
        try { return typeof mon !== 'undefined' ? mon.log : []; }
        catch(e) { return []; }
    }""")


def is_monitor_idle(page: Page) -> bool:
    """Check if the monitor shows 'Waiting for a query...'."""
    content = page.locator("#mon-content").inner_text()
    return "Waiting for a query" in content


def is_monitor_complete(page: Page) -> bool:
    """Check if the monitor shows 'Complete'."""
    content = page.locator("#mon-content").inner_text()
    return "Complete" in content


# ── Chat message inspection ──────────────────────────────────────────

def get_chat_messages(page: Page) -> list[dict[str, str]]:
    """Extract all chat messages as [{role, text}]."""
    return page.evaluate("""() => {
        const msgs = document.querySelectorAll('.message');
        return Array.from(msgs).map(m => ({
            role: m.classList.contains('user') ? 'user' : 'assistant',
            text: m.querySelector('.bubble')?.innerText || '',
            isIntermediate: m.classList.contains('intermediate'),
        }));
    }""")


def get_last_response(page: Page) -> str:
    """Get text content of the last assistant message."""
    msgs = page.locator(".message.assistant .bubble")
    if msgs.count() == 0:
        return ""
    return msgs.last.inner_text()


def count_messages(page: Page, role: str = "assistant") -> int:
    """Count messages by role."""
    return page.locator(f".message.{role}").count()


# ── Table inspection ─────────────────────────────────────────────────

def get_tables_in_response(page: Page) -> list[dict]:
    """Extract HTML tables from the last assistant response."""
    return page.evaluate("""() => {
        const msgs = document.querySelectorAll('.message.assistant');
        const last = msgs[msgs.length - 1];
        if (!last) return [];
        const tables = last.querySelectorAll('table');
        return Array.from(tables).map(t => {
            const headers = Array.from(t.querySelectorAll('th')).map(h => h.innerText);
            const rows = Array.from(t.querySelectorAll('tbody tr')).map(tr =>
                Array.from(tr.querySelectorAll('td')).map(td => td.innerText)
            );
            return { headers, rows, rowCount: rows.length };
        });
    }""")


# ── Follow-up interaction ────────────────────────────────────────────

def click_followup(page: Page, index: int = 0, timeout: float = 120_000) -> dict[str, Any]:
    """Click a follow-up suggestion button and wait for result."""
    followups = page.locator(".message.assistant:last-child .followup-btn")
    followups.nth(index).click()
    return wait_for_query_result(page, timeout)


def get_followup_texts(page: Page) -> list[str]:
    """Get text of follow-up suggestion buttons from the last message."""
    btns = page.locator(".message.assistant:last-child .followup-btn")
    return [btns.nth(i).text_content() for i in range(btns.count())]


# ── Screenshots ──────────────────────────────────────────────────────

def take_screenshot(page: Page, name: str, artifact_dir: Path | None = None):
    """Take a named screenshot."""
    if artifact_dir is None:
        artifact_dir = Path(__file__).parent / "artifacts" / "screenshots"
        artifact_dir.mkdir(parents=True, exist_ok=True)
    else:
        artifact_dir = artifact_dir / "screenshots"

    page.screenshot(
        path=str(artifact_dir / f"{name}.png"),
        full_page=True,
    )


def take_element_screenshot(page: Page, selector: str, name: str, artifact_dir: Path | None = None):
    """Take a screenshot of a specific element."""
    if artifact_dir is None:
        artifact_dir = Path(__file__).parent / "artifacts" / "screenshots"
        artifact_dir.mkdir(parents=True, exist_ok=True)
    else:
        artifact_dir = artifact_dir / "screenshots"

    element = page.locator(selector)
    if element.count() > 0:
        element.first.screenshot(path=str(artifact_dir / f"{name}.png"))


# ── Console & JS errors ─────────────────────────────────────────────

def collect_console_errors(page: Page) -> list[str]:
    """Collect JS console errors."""
    errors = []

    def _on_error(msg):
        if msg.type == "error":
            errors.append(msg.text)

    page.on("console", _on_error)
    return errors


def get_js_errors(page: Page) -> list[str]:
    """Get any JS errors that occurred on the page."""
    return page.evaluate("""() => {
        return window.__testErrors || [];
    }""")


# ── WebSocket helpers ────────────────────────────────────────────────

def wait_for_websocket_connected(page: Page, timeout: float = 15_000):
    """Wait until the WebSocket is connected."""
    page.wait_for_function(
        "() => typeof ws !== 'undefined' && ws !== null && ws.readyState === WebSocket.OPEN",
        timeout=timeout,
    )


def get_websocket_state(page: Page) -> str:
    """Get current WebSocket readyState as string."""
    state = page.evaluate("""() => {
        if (!window.ws) return 'none';
        const states = ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'];
        return states[window.ws.readyState] || 'unknown';
    }""")
    return state


# ── Mode selection ───────────────────────────────────────────────────

def select_mode(page: Page, mode: str):
    """Select a query mode from the sidebar dropdown."""
    page.locator("#mode-select").select_option(mode)


def get_selected_mode(page: Page) -> str:
    """Get the currently selected mode."""
    return page.locator("#mode-select").input_value()
