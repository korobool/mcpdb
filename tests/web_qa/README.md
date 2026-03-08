# Web QA Test Suite

End-to-end browser tests for `mcpdb web` using Playwright. Tests run real queries
against a live database and verify the full UI flow: source management, query
execution, chart rendering, monitor panel, follow-ups, and responsive layout.

## Prerequisites

```bash
pip install -e ".[dev]"
playwright install chromium
```

A running MySQL instance with the bgins database is required (default:
`mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins`). Override with the
`MCPDB_DATABASE_URL` env var.

## Running Tests

### Headless (CI mode)

```bash
pytest tests/web_qa/
```

Runs all 59 tests in headless Chromium. No display needed. Takes ~25 minutes
(real LLM queries).

### Headed (visual mode)

Watch tests execute in a real browser window:

```bash
# Quick start — opens browser with 300ms slowmo:
pytest tests/web_qa/ --visible

# Equivalent long form:
pytest tests/web_qa/ --headed --slowmo 300

# Custom slowmo (milliseconds between each action):
pytest tests/web_qa/ --headed --slowmo 500

# Run a single test visually:
pytest tests/web_qa/test_query_chart.py::TestChartQueries::test_bar_chart_renders --visible
```

Requires an X11 or Wayland display (`$DISPLAY` must be set).

### Recording Video

Record browser sessions as `.webm` files:

```bash
# Using our custom flag (saves to tests/web_qa/artifacts/videos/):
pytest tests/web_qa/ --record-video

# Using pytest-playwright's built-in flag:
pytest tests/web_qa/ --video on                  # always record
pytest tests/web_qa/ --video retain-on-failure    # only on failure

# Combine with headed mode to watch AND record:
pytest tests/web_qa/ --visible --record-video
```

Videos are saved to `tests/web_qa/artifacts/videos/` as `.webm` files.

### Selecting Tests

```bash
# Run only fast tests (skip extended/deep mode):
pytest tests/web_qa/ -m "not slow"

# Run specific test file:
pytest tests/web_qa/test_query_chart.py

# Run specific test class:
pytest tests/web_qa/test_monitor_panel.py::TestMonitorSteps

# Run specific test:
pytest tests/web_qa/test_source_lifecycle.py::TestDatabaseConnection::test_connect_database

# Run with verbose output:
pytest tests/web_qa/ -v
```

### Other Browsers

```bash
pytest tests/web_qa/ --browser firefox
pytest tests/web_qa/ --browser webkit
```

Install additional browsers first: `playwright install firefox webkit`.

## Test Structure

```
tests/web_qa/
├── conftest.py                 # Fixtures: server, browser config, auto-capture on failure
├── helpers.py                  # Reusable actions: connect_database, submit_query, etc.
├── test_source_lifecycle.py    #  6 tests — DB connect/remove, schema, starters
├── test_query_simple.py        #  9 tests — count/schema/aggregation, rendering, monitor
├── test_query_chart.py         #  3 tests — bar/pie/histogram chart rendering
├── test_query_modes.py         #  8 tests — mode selector, quick/simple/optimization/extended/deep
├── test_followups.py           #  3 tests — follow-up buttons, click interaction
├── test_error_handling.py      #  8 tests — empty query, no source, cancel, input behavior
├── test_monitor_panel.py       # 12 tests — phases, steps, timing, progress bar, completion
├── test_multi_query.py         #  5 tests — conversation flow, monitor reset, scroll
├── test_responsive.py          #  7 tests — desktop/tablet/narrow/mobile viewports
└── artifacts/                  # Auto-generated output
    ├── screenshots/            # Captured during tests (53 baseline images)
    ├── dom/                    # HTML snapshots on failure
    ├── traces/                 # Console log dumps on failure
    └── videos/                 # Recorded browser sessions
```

## Failure Diagnostics

When a test fails, the suite automatically captures:

- **Screenshot** — full-page PNG saved to `artifacts/screenshots/FAIL_<test_name>.png`
- **DOM snapshot** — raw HTML saved to `artifacts/dom/FAIL_<test_name>.html`
- **Console logs** — all browser console messages saved to `artifacts/traces/FAIL_<test_name>_console.json`

## Helper API

`helpers.py` provides reusable functions for writing new tests:

| Function | Description |
|----------|-------------|
| `connect_database(page, url)` | Connect a DB source via sidebar UI |
| `submit_query(page, question, mode)` | Type question, send, wait for result |
| `wait_for_query_result(page)` | Wait for current query to complete |
| `click_followup(page, index)` | Click a follow-up button, wait for result |
| `get_monitor_state(page)` | Read monitor panel state via JS |
| `get_monitor_log(page)` | Get activity log entries |
| `get_chat_messages(page)` | Extract all chat messages |
| `get_tables_in_response(page)` | Extract HTML tables from last response |
| `take_screenshot(page, name)` | Capture a named screenshot |
| `wait_for_websocket_connected(page)` | Wait until WS is ready |
