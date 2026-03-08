# MCPDB Productization Plan

## How to Run the Autonomous Session

### Quick Start

```bash
# From the mcpdb project root:
claude --dangerously-skip-permissions

# Then paste or reference this document:
# "Read PRODUCTIZATION.md and execute Phase 1"
```

### Claude Code Autonomous Mode Options

```bash
# Option 1: Skip all permission prompts (recommended for this session)
claude --dangerously-skip-permissions

# Option 2: Same thing via environment variable
CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS=true claude

# Option 3: With explicit model selection
claude --dangerously-skip-permissions --model claude-opus-4-6

# Option 4: Run a specific task non-interactively (fire-and-forget)
claude --dangerously-skip-permissions -p "Read PRODUCTIZATION.md and execute Phase 1"

# Option 5: Resume a prior session
claude --dangerously-skip-permissions --resume
```

### Prerequisites Before Starting

```bash
# 1. Activate environment
source .venv/bin/activate
source .run.sh  # loads GEMINI_API_KEY, MCPDB_DATABASE_URL

# 2. Verify everything works
python -m pytest tests/ -x -q          # should pass 998+ tests
mcpdb query "$MCPDB_DATABASE_URL" "how many tables are there?" --no-cache

# 3. Start Claude in autonomous mode
claude --dangerously-skip-permissions
```

### Session Persistence

Long sessions (hours) may hit context limits. Claude Code automatically compresses
prior context. To ensure continuity:

- Each phase writes results to `tests/productization/` (logs, reports, fixes)
- Progress is tracked in `tests/productization/PROGRESS.md`
- If context resets, Claude can read PROGRESS.md to resume where it left off

---

## Phase 1: Agentic Debug — Query Mode (All Source Types)

### Goal
Generate hundreds of test queries across db/csv/xlsx sources, run them with
advanced logging, and fix issues discovered in real time.

### 1.1 Test Query Generation

Generate query sets covering all modes and source types:

| Source Type | Source | Query Count | Coverage |
|------------|--------|-------------|----------|
| Database (MySQL) | bgins via $MCPDB_DATABASE_URL | 100 | All 5 modes |
| CSV | Generated test CSVs (sales, weather, logs) | 50 | simple, extended |
| Excel | Generated test .xlsx (multi-sheet, formulas) | 50 | simple, extended |
| Cross-source | CSV + DB federation | 20 | cross_source_query |

**Query categories** (per source type):
- Schema discovery (list tables, describe columns, ERD)
- Simple aggregations (counts, sums, averages, min/max)
- Temporal analysis (trends, year-over-year, date ranges)
- Distributions (histograms, percentiles, top-N)
- Joins and relationships (FK traversal, multi-table)
- Complex analytics (ratios, running totals, window functions)
- Edge cases (NULL handling, empty tables, unicode, large results)
- Chart generation (bar, line, scatter, histogram via Python sandbox)
- Optimization scenarios (full table scans, missing indexes)
- Deep investigations (multi-step research questions)

### 1.2 Execution Harness

```python
# tests/productization/run_query_battery.py
# Runs all queries with structured logging:
# - Full agent state at each node transition
# - LLM request/response pairs (token counts, latency)
# - SQL queries executed + row counts + timing
# - Sandbox execution results (stdout, stderr, charts)
# - Error traces with full context
# - Mode classification accuracy
# Output: tests/productization/results/{source_type}/{timestamp}.jsonl
```

**Logging levels:**
- `TRACE`: Every LLM call, every SQL execution, every state mutation
- `SUMMARY`: Per-query result (pass/fail, mode, steps, timing, errors)
- `ISSUES`: Only failures and anomalies for triage

### 1.3 Auto-Fix Protocol

When a query fails, the autonomous agent should:

1. **Classify the failure** (LLM error, SQL error, sandbox error, timeout, empty result)
2. **Check if it's a known pattern** (experience antipatterns)
3. **Determine if it's a code bug vs. a prompt issue**
4. **Apply the fix** (edit source code, update prompts, add error handling)
5. **Re-run the failing query** to verify the fix
6. **Run the full test suite** to ensure no regressions
7. **Commit the fix** with a descriptive message

### 1.4 Success Criteria

- [ ] 220+ queries generated and saved to `tests/productization/queries/`
- [ ] All queries executed with full logging
- [ ] Pass rate ≥ 90% across all source types
- [ ] All fixable failures addressed with commits
- [ ] Results report in `tests/productization/reports/phase1_report.md`

---

## Phase 2: Terminal Client UI/UX Overhaul

### Goal
Transform the CLI from a basic spinner into a rich, colorful, informative terminal experience.

### 2.1 Rich Terminal Output

Replace `_ConsoleProgress` braille spinner with a full Rich-based UI:

```
┌─ mcpdb query ──────────────────────────────────────────────┐
│ Q: What is the average claim amount by car brand?          │
│                                                            │
│ Mode: simple (auto-classified)                             │
│ Source: bgins (MySQL, 21 tables)                           │
├─ Pipeline ─────────────────────────────────────────────────┤
│ ✓ Classify   0.8s   → simple (3 entities detected)        │
│ ✓ Plan       2.1s   → 2 steps (SQL + SQL)                 │
│ ● Execute    Step 1/2 ━━━━━━━━━━━━━━━━━━━━ 100%           │
│   └─ SQL: SELECT brand, AVG(amount)... (234 rows, 0.3s)   │
│ ◌ Synthesize                                               │
├─ Result ───────────────────────────────────────────────────┤
│ The average claim amount by car brand:                     │
│                                                            │
│ | Brand    | Avg Amount | Count |                          │
│ |----------|-----------|-------|                            │
│ | Toyota   | 1,234.56  | 89    |                           │
│ | BMW      | 2,345.67  | 67    |                           │
│ | ...      | ...       | ...   |                           │
│                                                            │
│ 🕐 Total: 4.2s | Cache: miss | Steps: 2 | Debug: 0       │
└────────────────────────────────────────────────────────────┘

Suggestions:
  [1] Show the distribution as a chart
  [2] Which brand has the highest single claim?
  [3] Trend of claims by brand over time
```

### 2.2 Features to Implement

| Feature | Description | Library |
|---------|------------|---------|
| **Live pipeline** | Animated phase indicators (✓/●/◌/✗) | rich |
| **Progress bars** | Step execution progress with ETA | rich.progress |
| **Colored output** | Mode badges, status colors, syntax highlighting | rich.console |
| **Table rendering** | Pretty-printed result tables with alignment | rich.table |
| **Code panels** | SQL/Python shown in syntax-highlighted panels | rich.syntax |
| **Error panels** | Red-bordered panels with traceback context | rich.panel |
| **Chart rendering** | ASCII/Unicode charts for terminal (sparklines, bars) | plotext or uniplot |
| **Follow-ups** | Numbered suggestions, type number to run | input handling |
| **Timing footer** | Total time, cache status, step count, debug count | rich.text |
| **Streaming text** | Character-by-character synthesis output | rich.live |

### 2.3 REPL Mode (Interactive Shell)

```bash
mcpdb repl <conn>           # Enter interactive mode
mcpdb repl file.csv         # REPL with CSV source
mcpdb repl --multi          # Multi-source REPL
```

**REPL features:**
- Persistent session with conversation history
- Tab completion for table/column names
- `/mode <mode>` — force mode override
- `/source add <conn>` — add source mid-session
- `/source list` — show connected sources
- `/history` — show query history
- `/export <format>` — export last result (csv, json, markdown)
- `/cache stats` — show cache hit/miss stats
- `/schema [table]` — quick schema lookup
- `/erd` — render ERD in terminal (mermaid → ASCII)
- Up/down arrow for history navigation
- Ctrl+C to cancel running query (via CancellationToken)

### 2.4 Implementation Plan

1. Add `rich` to dependencies
2. Create `mcpdb/cli/` package:
   - `mcpdb/cli/progress.py` — Rich-based progress display (replaces `_ConsoleProgress`)
   - `mcpdb/cli/renderer.py` — Result rendering (tables, charts, code, errors)
   - `mcpdb/cli/repl.py` — Interactive REPL with prompt_toolkit
3. Wire into `__main__.py` (new `repl` command)
4. Preserve backward compat: `mcpdb query` still works as one-shot

### 2.5 Success Criteria

- [ ] Rich pipeline display with live updates
- [ ] Colorized output for all query modes
- [ ] REPL mode with tab completion and history
- [ ] ASCII chart rendering for terminal environments
- [ ] Follow-up suggestions with number selection
- [ ] All existing tests still pass
- [ ] New tests for CLI rendering components

---

## Phase 3: Agentic Debug — Web Client (Browser Automation)

### Goal
Use Playwright (preferred over Selenium for modern async support) to automatically
test the web client end-to-end, including UI interactions, screenshots, and visual
regression detection.

### 3.1 Browser Test Framework

```python
# tests/productization/web/test_web_e2e.py
# Uses Playwright for browser automation:
# - Launch mcpdb web server
# - Open browser, navigate to UI
# - Perform interactions (type queries, upload files, click buttons)
# - Capture screenshots at each step
# - Assert on DOM state, WebSocket messages, visual output
# - Detect UI regressions via screenshot comparison
```

### 3.2 Test Scenarios

| Category | Tests | What's Validated |
|----------|-------|-----------------|
| **Source Management** | Add DB, upload CSV, upload Excel, remove source | Sidebar updates, sample data, ERD |
| **Query Execution** | All 5 modes, cancel mid-query, error handling | Monitor updates, result rendering, timing |
| **Chart Rendering** | Python sandbox charts, Mermaid diagrams | Image display, responsive sizing |
| **Real-time Streaming** | WebSocket events, progress indicators | Monitor panel accuracy, no stale state |
| **Follow-ups** | Click suggestion, submit, verify new query | Suggestion buttons work, new result appears |
| **Responsive Layout** | Resize to mobile/tablet/desktop widths | 3-column → 2-column → 1-column collapse |
| **Error States** | Invalid SQL, timeout, disconnection | Error messages, reconnect behavior |
| **Multi-query** | Submit multiple queries in sequence | Chat history preserved, sources maintained |
| **File Upload** | Drag-drop CSV, large file (>100MB), invalid file | Upload progress, error messages, cleanup |
| **Theme/Accessibility** | Dark theme consistency, keyboard navigation | Contrast ratios, focus management |

### 3.3 Screenshot Analysis

For each test scenario:
1. **Capture** screenshot at key moments (before/after query, on error, etc.)
2. **Store** in `tests/productization/web/screenshots/`
3. **Compare** with baseline (pixel diff + structural similarity)
4. **Flag** visual regressions (>5% pixel difference threshold)
5. **Generate** visual report HTML with side-by-side comparisons

### 3.4 Auto-Fix Protocol for Web Issues

When a web test fails:
1. Capture screenshot + DOM snapshot + console logs + WebSocket messages
2. Analyze the failure: JS error? CSS layout? Backend error? Timeout?
3. If CSS: fix in `index.html` inline styles
4. If JS: fix in `index.html` inline scripts
5. If backend: fix in `app.py` endpoint
6. Re-run the specific test to verify
7. Run full web test suite to ensure no regressions

### 3.5 Success Criteria

- [ ] Playwright test suite with 30+ scenarios
- [ ] Screenshot baseline established for all key states
- [ ] All source types testable (DB, CSV, Excel)
- [ ] All query modes exercised end-to-end
- [ ] Visual regression detection working
- [ ] CI-compatible (headless browser)
- [ ] Report in `tests/productization/reports/phase3_report.md`

---

## Phase 4: Large Database Optimization & Stress Testing

### Goal
Test and harden mcpdb against large databases where naive queries will timeout,
tables lack indexes, and smart analytics strategies are required.

### 4.1 Large DB Test Setup

```python
# tests/productization/large_db/setup_large_db.py
# Generate a SQLite database with:
# - 5M row "transactions" table (no indexes beyond PK)
# - 1M row "customers" table with demographics
# - 500K row "products" table with categories
# - 10M row "events" table (time-series, append-only)
# - Complex FKs, NULLable columns, skewed distributions
```

### 4.2 Optimization Scenarios

| Scenario | Challenge | Expected Behavior |
|----------|-----------|-------------------|
| **Full scan on 5M rows** | `SELECT AVG(amount) FROM transactions` | Mode: optimization, use sampling |
| **Unindexed JOIN** | Join customers × transactions on non-indexed FK | Detect slow join, suggest/create temp index |
| **Time-range without index** | `WHERE created_at BETWEEN '2024-01' AND '2024-03'` | Recognize full scan, add date filter strategy |
| **GROUP BY high-cardinality** | `GROUP BY customer_id` on 5M rows | Use approximate counts or sampling |
| **Subquery on large table** | Correlated subquery on 10M events | Rewrite as JOIN or CTE |
| **Multiple large joins** | 3+ large table joins without indexes | Detect, warn, use staged approach |
| **Count(DISTINCT)** | On 5M rows, unindexed column | Use HyperLogLog approximation hint |
| **Export large result** | Query returns 100K+ rows | Streaming/pagination, not full materialization |

### 4.3 Smart Analytics Strategies

Enhance the optimization mode to:

1. **Pre-flight cost estimation**: EXPLAIN ANALYZE before execution
2. **Adaptive sampling**: Start with 1% sample, scale up if variance is high
3. **Index awareness**: Read available indexes, route queries to indexed columns
4. **Timeout escalation**: 10s → warn → suggest sampling → auto-sample
5. **Result size management**: Stream large results, paginate in synthesis
6. **Memory-aware execution**: Track DataFrame sizes, spill to DuckDB if needed

### 4.4 Stress Test Battery

```python
# tests/productization/large_db/stress_test.py
# 50 queries designed to stress the system:
# - 10 full-scan queries (should trigger optimization mode)
# - 10 complex joins (should use staged execution)
# - 10 time-series queries (should use date partitioning)
# - 10 aggregation queries (should use sampling for large tables)
# - 10 mixed queries (joins + aggregations + subqueries)
# Each query has:
# - Expected mode classification
# - Maximum acceptable execution time
# - Minimum result quality threshold
```

### 4.5 Success Criteria

- [ ] Large DB generated with realistic data distributions
- [ ] 50 stress queries defined with expected behavior
- [ ] Optimization mode correctly detects large table operations
- [ ] No query times out without a user-friendly explanation
- [ ] Sampling strategies produce results within 10% of exact answers
- [ ] Report in `tests/productization/reports/phase4_report.md`

---

## Phase 5: REPL Mode with Pseudographic Window Interface

### Goal
Build a terminal UI (TUI) using a library like Textual that provides a windowed
interface for interactive productization sessions.

### 5.1 TUI Layout

```
╔══ MCPDB Productization Console ════════════════════════════╗
║ ┌─ Sources ──────┐ ┌─ Query ───────────────────────────┐  ║
║ │ ● bgins (MySQL)│ │ > What is the average claim...    │  ║
║ │ ○ sales.csv    │ │                                   │  ║
║ │ ○ report.xlsx  │ │ [Enter] Send  [Ctrl+C] Cancel     │  ║
║ └────────────────┘ └───────────────────────────────────┘  ║
║ ┌─ Pipeline ─────────────────────────────────────────────┐ ║
║ │ Classify ━━ Plan ━━ Execute [2/3] ━━ Synthesize        │ ║
║ │ Step 2: SELECT brand, AVG(amount)... ● running 1.2s    │ ║
║ └────────────────────────────────────────────────────────┘ ║
║ ┌─ Result ───────────────────────────────────────────────┐ ║
║ │ | Brand  | Avg Amount | Count |                        │ ║
║ │ |--------|-----------|-------|                          │ ║
║ │ | Toyota | 1,234.56  |  89   |                         │ ║
║ │ | BMW    | 2,345.67  |  67   |                         │ ║
║ │                                                        │ ║
║ │ Suggestions: [1] Chart  [2] Top claims  [3] Trend     │ ║
║ └────────────────────────────────────────────────────────┘ ║
║ ┌─ Log ──────────────────────────────────────────────────┐ ║
║ │ 14:23:01 classify/complete mode=simple 0.8s            │ ║
║ │ 14:23:03 plan/ready 2 steps                            │ ║
║ │ 14:23:04 step/complete step=1 sql 234 rows 0.3s       │ ║
║ └────────────────────────────────────────────────────────┘ ║
╚════════════════════════════════════════════════════════════╝
```

### 5.2 Technology: Textual

```toml
# Add to pyproject.toml [project.optional-dependencies]
tui = ["textual>=0.50", "rich>=13.0"]
```

**Why Textual:**
- Pure Python, no ncurses binding issues
- Built on Rich (already planned for Phase 2)
- Async-native (perfect for WebSocket/agent callbacks)
- CSS-like styling, reactive widgets, built-in scrolling
- Works over SSH, in tmux, and in VS Code terminal

### 5.3 TUI Components

| Widget | Purpose |
|--------|---------|
| `SourcePanel` | List connected sources, add/remove, show schema |
| `QueryInput` | Multi-line text input with history, tab completion |
| `PipelineBar` | Animated phase indicators with timing |
| `ResultView` | Scrollable markdown/table/chart rendering |
| `LogPanel` | Real-time event log with filtering |
| `StatsFooter` | Cache hits, total queries, error rate, uptime |

### 5.4 Productization Console Extensions

Beyond normal REPL, the TUI can include productization-specific panels:

| Panel | Purpose |
|-------|---------|
| `TestRunner` | Run query batteries, show pass/fail in real time |
| `IssueTracker` | List discovered issues, mark as fixed/wontfix |
| `CoverageMap` | Show which query categories have been tested |
| `FixLog` | Track code changes made during the session |

### 5.5 Success Criteria

- [ ] Textual-based TUI launches with `mcpdb tui <conn>`
- [ ] All panels render correctly and update in real time
- [ ] Query execution with full pipeline visibility
- [ ] Log panel shows all agent events
- [ ] Works in standard terminals (80x24 minimum)
- [ ] Keyboard navigation between panels

---

## Execution Order & Dependencies

```
Phase 2 (Terminal UI/UX) ──→ Phase 5 (TUI REPL)
     │                            │
     ▼                            ▼
Phase 1 (Query Battery) ←── Uses REPL to run batteries
     │
     ▼
Phase 4 (Large DB) ←── Reuses harness from Phase 1
     │
Phase 3 (Web Browser Tests) ── Independent, can run in parallel
```

**Recommended execution order:**
1. **Phase 2** first — Rich terminal output improves all subsequent debugging
2. **Phase 1** — Query battery reveals most bugs
3. **Phase 4** — Large DB stress testing (builds on Phase 1 harness)
4. **Phase 3** — Web browser automation (independent, can overlap)
5. **Phase 5** — TUI REPL (builds on Phase 2's Rich components)

---

## Autonomous Session Instructions

When Claude starts in `--dangerously-skip-permissions` mode:

```
Read PRODUCTIZATION.md.
Execute phases in order (2 → 1 → 4 → 3 → 5).

For each phase:
1. Read the phase requirements
2. Create the directory structure under tests/productization/
3. Implement the code
4. Run it
5. Fix any issues discovered
6. Write a summary report
7. Update tests/productization/PROGRESS.md
8. Commit with a descriptive message
9. Move to the next phase

If you hit a context limit, read PROGRESS.md to resume.
If a test requires external resources (real DB), use $MCPDB_DATABASE_URL.
If a test requires browser automation, install Playwright first.
Always run `python -m pytest tests/ -x -q` before committing to ensure no regressions.
```

### Time Estimates

| Phase | Estimated Duration | Can Run Unattended |
|-------|-------------------|-------------------|
| Phase 2 | 1-2 hours | Yes |
| Phase 1 | 2-4 hours | Yes (needs DB access) |
| Phase 4 | 1-2 hours | Yes |
| Phase 3 | 2-3 hours | Yes (needs display or Xvfb) |
| Phase 5 | 1-2 hours | Yes |
| **Total** | **7-13 hours** | **Yes** |

---

## File Structure

```
tests/productization/
├── PROGRESS.md                    # Session progress tracker
├── queries/
│   ├── db_queries.json            # 100 database queries
│   ├── csv_queries.json           # 50 CSV queries
│   ├── xlsx_queries.json          # 50 Excel queries
│   └── cross_source_queries.json  # 20 cross-source queries
├── run_query_battery.py           # Phase 1 harness
├── results/
│   ├── db/                        # Database query results
│   ├── csv/                       # CSV query results
│   └── xlsx/                      # Excel query results
├── large_db/
│   ├── setup_large_db.py          # Phase 4 DB generator
│   └── stress_test.py             # Phase 4 stress queries
├── web/
│   ├── test_web_e2e.py            # Phase 3 Playwright tests
│   ├── screenshots/               # Baseline + current screenshots
│   └── conftest.py                # Playwright fixtures
├── reports/
│   ├── phase1_report.md
│   ├── phase2_report.md
│   ├── phase3_report.md
│   ├── phase4_report.md
│   └── phase5_report.md
└── fixtures/
    ├── sales_data.csv             # Test CSV
    ├── weather_data.csv           # Test CSV
    └── multi_sheet_report.xlsx    # Test Excel
```
