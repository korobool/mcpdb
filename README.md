# MCPDB

**MCP server for natural language database exploration and analysis.**

MCPDB lets you connect databases, CSVs, and Excel files to AI assistants (like Claude Desktop) through the [Model Context Protocol](https://modelcontextprotocol.io). Ask questions in plain English — MCPDB generates SQL, runs it, visualizes results, and explains findings.

## Features

- **5 Thinking Modes** — Quick (schema-only), Simple (plan-execute), Extended (with checkpoints), Optimization (cost-aware sampling), Deep Analysis (multi-investigation research)
- **5 Database Dialects** — PostgreSQL, MySQL, SQLite, MSSQL, Oracle
- **CSV & Excel Support** — Load files into DuckDB for SQL querying, cross-source federation
- **33 MCP Tools** — Session management, querying, discovery, profiling, relationships, Excel operations, analysis, export, experience management, execution control
- **Python Sandbox** — Secure code execution for data transformations and chart generation
- **Experience System** — Caches successful queries, learns from failures, transfers knowledge across sources
- **Cost Gate** — EXPLAIN-based cost estimation with user approval for expensive queries
- **Streaming** — Real-time token streaming and step-by-step execution progress
- **Web UI** — NiceGUI-based interface with schema viewer, chat, artifact display, and export
- **Export** — Conversations to HTML, PDF, or Jupyter notebooks

## Installation

Requires Python 3.10+.

```bash
pip install mcpdb
```

### Optional Dependencies

Install only what you need:

```bash
pip install mcpdb[csv]       # CSV support (DuckDB, chardet)
pip install mcpdb[excel]     # Excel support (openpyxl)
pip install mcpdb[ui]        # Web UI (NiceGUI)
pip install mcpdb[export]    # PDF/notebook export (weasyprint, nbformat)
pip install mcpdb[sandbox]   # Chart generation (matplotlib, seaborn)
pip install mcpdb[openai]    # OpenAI provider
pip install mcpdb[gemini]    # Google Gemini provider
pip install mcpdb[ollama]    # Ollama local models (httpx)
pip install mcpdb[oracle]    # Oracle database (cx_Oracle)
pip install mcpdb[all]       # Everything except Oracle
```

### Development Install

```bash
git clone https://github.com/korobool/mcpdb.git
cd mcpdb
pip install -e ".[dev,all]"
```

## Quick Start

### 1. With Claude Desktop (recommended)

Add to your Claude Desktop configuration (`~/.claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "mcpdb": {
      "command": "mcpdb",
      "args": ["serve"]
    }
  }
}
```

Restart Claude Desktop. You can now ask Claude to connect a database and explore it:

> "Connect to postgresql://user:pass@localhost/mydb and show me the top 10 customers by revenue"

### 2. One-shot Query

```bash
mcpdb query "sqlite:///mydata.db" "What are the top 5 products by sales?"
```

### 3. Web UI

```bash
mcpdb ui
# Opens http://localhost:8080
```

## CLI Reference

```
mcpdb                          Print version
mcpdb serve                    Start MCP server (stdio, for Claude Desktop)
mcpdb serve --transport sse    Start MCP server (SSE, for web clients)
mcpdb serve --port 8765        Start SSE server on custom port
mcpdb ui                       Start the web UI
mcpdb ui --port 8080           Start UI on custom port
mcpdb query <conn> <question>  One-shot query mode
mcpdb --help                   Show help
mcpdb --version                Show version
```

### Starting & Stopping

**MCP stdio server** (for Claude Desktop):
```bash
mcpdb serve
# Runs in foreground, reads/writes on stdin/stdout
# Stop with Ctrl+C
```

**SSE server** (for web clients):
```bash
mcpdb serve --transport sse --port 8765
# Stop with Ctrl+C
```

**Web UI**:
```bash
mcpdb ui --port 8080
# Opens browser automatically
# Stop with Ctrl+C
```

To run as a background service:
```bash
nohup mcpdb serve --transport sse --port 8765 > mcpdb.log 2>&1 &
# Stop with: kill $(pgrep -f "mcpdb serve")
```

## Configuration

MCPDB loads configuration from YAML. Search order:

1. Explicit path via `MCPDB_CONFIG` environment variable
2. `./mcpdb.yaml` in the current directory
3. Built-in defaults (no file needed)

### Example `mcpdb.yaml`

```yaml
llm:
  reasoning:
    provider: anthropic           # anthropic, openai, gemini, ollama
    model: claude-sonnet-4-6
    api_key: ${ANTHROPIC_API_KEY} # Environment variable resolution
  fast:
    model: claude-haiku-4-5-20251001
  temperature: 0.0
  timeout: 120
  budget_per_question_usd: 2.00

server:
  transport: stdio                # stdio or sse
  host: localhost
  port: 8765

execution:
  query_timeout: 30               # SQL timeout in seconds
  python_timeout: 60              # Sandbox timeout in seconds
  max_rows_display: 100
  read_only: true                 # Block INSERT/UPDATE/DELETE/DROP

cost_gate:
  enabled: true
  auto_mode: false                # true = auto-select strategy without asking
  large_table_threshold: 1000000  # Rows before cost gate triggers

duckdb:
  memory_limit: 2GB
  threads: 4

experience:
  enabled: true
  storage_dir: ~/.mcpdb/experience
  cache_max_age_days: 30

ui:
  theme: dark                     # dark or light
  port: 8080
```

Environment variables are resolved with `${VAR_NAME}` syntax — use this for API keys.

## Debug / Development Mode

### Logging

MCPDB logs to stderr. Control verbosity with the `MCPDB_LOG_LEVEL` environment variable:

```bash
# Debug logging — shows all LLM calls, SQL execution, agent state transitions
MCPDB_LOG_LEVEL=DEBUG mcpdb serve

# Warning only
MCPDB_LOG_LEVEL=WARNING mcpdb serve
```

Log format: `2025-01-15 10:30:45 [DEBUG] mcpdb.agent.graph: classify → simple mode`

### Running Tests

```bash
# Run all tests
python -m pytest

# Run a specific test file
python -m pytest tests/test_agent.py

# Run with verbose output
python -m pytest -v

# Run tests matching a pattern
python -m pytest -k "test_cost"
```

The test suite has 890+ tests covering all modules. Tests use pytest with `pytest-asyncio` for async code.

### Development Workflow

```bash
# Install in editable mode with dev dependencies
pip install -e ".[dev,all]"

# Run tests continuously during development
python -m pytest --tb=short -q

# Check a specific module
python -m pytest tests/test_security.py -v
```

### Debugging the Agent

To trace agent execution step by step:

```bash
MCPDB_LOG_LEVEL=DEBUG mcpdb query "sqlite:///test.db" "How many rows in users?"
```

This will print:
- Classification result (which thinking mode was selected)
- Planning output (SQL/Python steps)
- Each execution step with timing
- Synthesis and final response

### Debugging MCP Communication

For stdio transport, the MCP protocol messages go through stdin/stdout. To inspect them:

```bash
# Use the MCP Inspector tool
npx @modelcontextprotocol/inspector mcpdb serve
```

## Architecture

```
mcpdb/
├── __main__.py          # CLI entry point
├── config.py            # YAML config loader with env var resolution
├── logging.py           # Logging setup
├── agent/               # LangGraph agent orchestration
│   ├── graph.py         # Main agent graph (classify → mode → synthesize)
│   ├── state.py         # AgentState TypedDict
│   ├── nodes/           # Individual graph nodes
│   │   ├── classify.py  # Question → mode routing
│   │   ├── common.py    # Plan, execute, debug, synthesize factories
│   │   └── validators.py# Result validation, replanning
│   ├── subgraphs/       # Mode-specific subgraphs
│   │   ├── quick.py     # Schema-only answers
│   │   ├── simple.py    # Plan → execute → synthesize
│   │   ├── extended.py  # With checkpoints + reflection
│   │   └── optimization.py # Cost-aware with sampling
│   ├── deep_analysis.py # Multi-investigation research mode
│   └── cancellation.py  # CancellationToken, mid-execution abort
├── sources/             # Data source abstraction layer
│   ├── base.py          # DataSource, QueryableSource, SpreadsheetSource ABCs
│   ├── registry.py      # SourceRegistry (add/remove/get sources)
│   ├── database/        # SQL database support
│   │   ├── source.py    # DatabaseSource implementation
│   │   ├── connector.py # SQLAlchemy engine + connection pooling
│   │   ├── schema_explorer.py # Introspection (tables, columns, PKs, FKs)
│   │   └── dialects/    # PostgreSQL, MySQL, SQLite, MSSQL, Oracle
│   ├── csv/             # CSV → DuckDB support
│   │   ├── source.py    # CsvSource implementation
│   │   ├── loader.py    # Encoding/delimiter detection
│   │   └── duckdb_backend.py
│   └── excel/           # Excel workbook support
│       ├── source.py    # ExcelSource implementation
│       ├── workbook_reader.py  # openpyxl reader
│       ├── structure_analyzer.py # Table vs text region detection
│       ├── formula_deps.py     # Formula dependency graphs
│       ├── formula_clusters.py # Similar formula detection
│       └── multi_workbook.py   # Multi-file management
├── mcp/                 # MCP protocol layer
│   ├── server.py        # Server creation + stdio/SSE transport
│   ├── resources.py     # MCP resources (schema://, erd://, session://)
│   ├── prompts.py       # MCP prompts (explore_source, deep_table_analysis)
│   └── tools/           # 33 MCP tools across 10 categories
│       ├── session.py   # connect_database, list_sources, remove_source, ...
│       ├── querying.py  # execute_sql, get_table_sample, validate_sql, ...
│       ├── discovery.py # search_schema, explain_query, render_erd
│       ├── profiling.py # profile_table, profile_column
│       ├── relationships.py # find_relationships, suggest_joins
│       ├── excel.py     # load_excel, list_sheets, read_range, ...
│       ├── analysis.py  # ask_question, ask_deep_question
│       ├── export.py    # export_conversation
│       ├── experience.py # get_experience_stats, vote_response, ...
│       └── control.py   # cancel_execution, add_context, submit_strategy
├── llm/                 # LLM provider abstraction
│   ├── provider.py      # LLMProvider ABC + AnthropicProvider
│   ├── openai_provider.py
│   ├── gemini_provider.py
│   ├── ollama_provider.py
│   └── factory.py       # create_provider() + FallbackProvider
├── sandbox/             # Secure Python execution
│   ├── executor.py      # Subprocess-based execution
│   └── security.py      # Import validation, resource limits
├── security/            # Security hardening
│   ├── sql_safety.py    # Read-only enforcement, injection detection
│   ├── credentials.py   # Connection string redaction
│   └── rate_limiter.py  # Rate/concurrency limits, circuit breaker
├── experience/          # Learning system
│   ├── store.py         # JSONL storage per source
│   ├── cache.py         # Exact-match response cache
│   ├── fingerprint.py   # Source identity hashing
│   ├── retriever.py     # Semantic similarity search
│   ├── embeddings.py    # Embedding providers
│   ├── strategy_records.py  # Cost gate strategy tracking
│   ├── cross_dialect.py     # Cross-source pattern sharing
│   └── schema_drift.py     # Schema change detection
├── session/             # Session lifecycle
│   └── session_manager.py # Persistent sessions with disk storage
├── export/              # Conversation export
│   ├── html_export.py   # Standalone HTML rendering
│   ├── pdf_export.py    # PDF via weasyprint
│   └── notebook_export.py # Jupyter notebook generation
└── ui/                  # Web interface (NiceGUI)
    ├── app.py           # Application layout + routing
    └── components/      # UI components
        ├── chat.py
        ├── source_panel.py
        ├── schema_viewer.py
        ├── excel_viewer.py
        ├── artifact_viewer.py
        ├── execution_monitor.py
        ├── deep_analysis_viewer.py
        ├── cost_gate_dialog.py
        └── export_dialog.py
```

## Thinking Modes

MCPDB automatically classifies your question and routes to the appropriate mode:

| Mode | When Used | Steps |
|------|-----------|-------|
| **Quick** | Metadata questions ("How many tables?") | Answer from schema context only |
| **Simple** | Standard queries ("Top 10 customers") | Plan → Execute → Synthesize |
| **Extended** | Complex analysis ("Comprehensive churn analysis") | Plan → Execute with checkpoints → Reflect → Synthesize |
| **Optimization** | Large table queries (>1M rows) | Cost check → Strategy gate → Sample/Full → Execute |
| **Deep** | Research questions ("Investigate revenue patterns") | Blueprint → Multiple investigations → Reasoning → Report |

## MCP Tools

### Session (6 tools)
`connect_database`, `connect_csv`, `connect_excel`, `list_sources`, `remove_source`, `get_source_schema`

### Querying (4 tools)
`execute_sql`, `get_table_sample`, `validate_sql`, `search_data`

### Discovery (3 tools)
`search_schema`, `explain_query`, `render_erd`

### Profiling (2 tools)
`profile_table`, `profile_column`

### Relationships (2 tools)
`find_relationships`, `suggest_joins`

### Excel (5 tools)
`load_excel`, `list_sheets`, `read_range`, `extract_excel_table`, `explain_formula`

### Analysis (2 tools)
`ask_question`, `ask_deep_question`

### Export (1 tool)
`export_conversation` — HTML, PDF, or Jupyter notebook

### Experience (5 tools)
`get_experience_stats`, `list_cached_queries`, `invalidate_cache_entry`, `clear_experience`, `vote_response`

### Control (3 tools)
`cancel_execution`, `add_context`, `submit_strategy`

## Supported Data Sources

### Databases

```
postgresql://user:pass@host:5432/dbname
mysql://user:pass@host:3306/dbname
sqlite:///path/to/database.db
mssql+pyodbc://user:pass@host/dbname?driver=ODBC+Driver+17+for+SQL+Server
oracle://user:pass@host:1521/service
```

### CSV Files

Loaded via the `connect_csv` tool or `load_csv_files` — auto-detects encoding, delimiters, and headers. Multiple CSVs can be loaded into the same DuckDB session for cross-file joins.

### Excel Files

Loaded via the `load_excel` tool. Supports:
- Multi-sheet workbooks
- Automatic table detection vs. text regions
- Formula extraction and explanation
- Cell grid rendering for non-tabular layouts
- Multiple workbooks with cross-workbook references

## Security

- **Read-only mode** (default): Blocks INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE
- **SQL injection detection**: Flags suspicious patterns (stacked queries, INTO OUTFILE, etc.)
- **Python sandbox**: Subprocess isolation with import allowlist, resource limits (memory, CPU, no file/network access)
- **Credential redaction**: Connection strings and API keys are stripped from logs
- **Rate limiting**: Configurable per-session query rate and concurrency limits
- **Circuit breaker**: Automatic backoff on repeated LLM or database failures

## License

MIT
