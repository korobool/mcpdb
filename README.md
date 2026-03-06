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
- **Web Client** — FastAPI + WebSocket web app with 3-panel layout, real-time execution monitor, chart rendering, and markdown
- **Export** — Conversations to HTML, PDF, or Jupyter notebooks

## Installation

Requires Python 3.10+.

```bash
pip install mcpdb
```

### Optional Dependencies

Install only what you need:

**Database drivers** (install for your database type):
```bash
pip install mcpdb[postgresql]  # PostgreSQL (psycopg2-binary)
pip install mcpdb[mysql]       # MySQL / MariaDB (PyMySQL)
pip install mcpdb[mssql]       # SQL Server (pyodbc)
pip install mcpdb[oracle]      # Oracle (cx_Oracle)
# SQLite — built-in, no extra install needed
```

**Data sources & features**:
```bash
pip install mcpdb[csv]         # CSV support (DuckDB, chardet)
pip install mcpdb[excel]       # Excel support (openpyxl)
pip install mcpdb[web]         # Web client (FastAPI + Uvicorn)
pip install mcpdb[export]      # PDF/notebook export (weasyprint, nbformat)
pip install mcpdb[sandbox]     # Charts & ML (matplotlib, seaborn, scikit-learn, scipy)
```

**LLM providers** (Gemini is the default; Anthropic is included):
```bash
pip install mcpdb[gemini]      # Google Gemini models (google-genai SDK, default provider)
pip install mcpdb[openai]      # OpenAI GPT models
pip install mcpdb[ollama]      # Ollama local models (httpx)
```

**Install everything** (except Oracle):
```bash
pip install mcpdb[all]
```

You can combine extras: `pip install mcpdb[postgresql,mysql,csv,excel]`

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

### 3. Web Client

```bash
mcpdb web
# Auto-selects a free port, opens browser
```

The web client is a 3-panel interface: data sources & schema on the left, chat in the center, and execution monitor on the right. It auto-selects an available port (starting from 8080), auto-connects to a database if `MCPDB_DATABASE_URL` is set, and picks up the Gemini API key from `GEMINI_API_KEY`.

```bash
# Quick start — export your env vars and launch
export GEMINI_API_KEY="your-key"
export MCPDB_DATABASE_URL="postgresql://user:pass@localhost/mydb"
mcpdb web
```

## CLI Reference

```
mcpdb                          Print version
mcpdb serve                    Start MCP server (stdio, for Claude Desktop)
mcpdb serve --transport sse    Start MCP server (SSE, for web clients)
mcpdb serve --port 8765        Start SSE server on custom port
mcpdb web                      Start web client (recommended)
mcpdb web --port 8080          Web client on custom port
mcpdb web --no-browser         Start without opening browser
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

**Web client** (recommended):
```bash
mcpdb web
# Auto-selects a free port (starting from 8080), opens browser
# Auto-connects to MCPDB_DATABASE_URL if set
# Uses GEMINI_API_KEY (or other provider keys) from environment
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
    provider: gemini              # gemini, openai, anthropic, ollama
    model: gemini-2.5-pro
    api_key: ${GEMINI_API_KEY}    # Environment variable resolution
  fast:
    model: gemini-2.5-flash
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

sandbox:
  allowed_modules: []             # Extra modules to allow (added to defaults)
  blocked_modules: []             # Extra modules to block (added to defaults)
  allow_all: false                # true = allow all imports except blocklist
  memory_mb: 2048                 # Subprocess memory limit
  cpu_seconds: 60                 # Subprocess CPU time limit
```

Environment variables are resolved with `${VAR_NAME}` syntax — use this for API keys.

### Using Google Gemini

1. Get an API key from [Google AI Studio](https://aistudio.google.com/apikey).

2. Install the Gemini extra:
   ```bash
   pip install mcpdb[gemini]   # installs google-genai SDK
   ```

3. Set your API key as an environment variable:
   ```bash
   export GEMINI_API_KEY="your-key-here"
   ```

4. Gemini is the default provider. If you want to customize:
   ```yaml
   llm:
     reasoning:
       provider: gemini
       model: gemini-2.5-pro         # or gemini-2.5-flash, gemini-2.0-flash
       api_key: ${GEMINI_API_KEY}
     fast:
       provider: gemini
       model: gemini-2.5-flash
       api_key: ${GEMINI_API_KEY}
   ```

   Or for Claude Desktop, pass the key via environment in your MCP config:
   ```json
   {
     "mcpServers": {
       "mcpdb": {
         "command": "mcpdb",
         "args": ["serve"],
         "env": {
           "GEMINI_API_KEY": "your-key-here",
           "MCPDB_CONFIG": "/path/to/mcpdb.yaml"
         }
       }
     }
   }
   ```

### Using OpenAI

```bash
export OPENAI_API_KEY="sk-..."
pip install mcpdb[openai]
```

```yaml
llm:
  reasoning:
    provider: openai
    model: gpt-4.1
    api_key: ${OPENAI_API_KEY}
```

### Using Ollama (local models)

```bash
pip install mcpdb[ollama]
ollama pull llama3.1        # Download a model first
```

```yaml
llm:
  reasoning:
    provider: ollama
    model: llama3.1          # Any model available in your Ollama instance
```

No API key needed — Ollama runs locally on `http://localhost:11434`.

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

The test suite has 900+ tests covering all modules. Tests use pytest with `pytest-asyncio` for async code.

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
│   ├── provider.py      # LLMProvider ABC, _extract_json()
│   ├── gemini_provider.py  # Google Gemini (default)
│   ├── openai_provider.py  # OpenAI GPT
│   ├── anthropic_provider.py # Anthropic Claude
│   ├── ollama_provider.py  # Ollama local models
│   └── factory.py       # create_provider() factory
├── sandbox/             # Secure Python execution
│   ├── executor.py      # Subprocess-based execution
│   └── security.py      # Configurable import allowlist/blocklist, resource limits
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
├── web/                 # Web client (FastAPI + WebSocket)
│   ├── app.py           # FastAPI REST + WebSocket + event streaming
│   └── templates/       # Single-page HTML template
├── session/             # Session lifecycle
│   └── session_manager.py # Persistent sessions with disk storage
└── export/              # Conversation export
    ├── html_export.py   # Standalone HTML rendering
    ├── pdf_export.py    # PDF via weasyprint
    └── notebook_export.py # Jupyter notebook generation
```

## Web Client

The web client is an interactive interface for exploring your data. It runs a FastAPI backend with WebSocket event streaming and serves a single-page HTML template — no build step, no npm.

### Features

- **3-panel layout** — Data sources & schema (left), chat (center), execution monitor (right)
- **Source management** — Connect databases, upload CSV/Excel files from the UI
- **Schema browser** — Expandable tree of tables/columns with inline data preview and ERD
- **6 query modes** — Auto, Quick, Simple, Optimize, Extended, Deep — selectable per query
- **Real-time execution monitor** — Watch classification, planning, step execution, and synthesis as they happen
- **Chart rendering** — Python-generated matplotlib/seaborn charts displayed as images
- **Deep mode streaming** — Investigation results streamed as they complete
- **Markdown responses** — Syntax-highlighted code blocks, Mermaid diagrams, GFM tables
- **Follow-up suggestions** — Context-aware follow-up questions after every response

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` | Auto-used by default Gemini provider |
| `OPENAI_API_KEY` | Used when switching to OpenAI provider |
| `ANTHROPIC_API_KEY` | Used when switching to Anthropic provider |
| `MCPDB_DATABASE_URL` | Auto-connects this database on startup |

### Quick Start

```bash
# Set your API key and database
export GEMINI_API_KEY="your-key"
export MCPDB_DATABASE_URL="postgresql://user:pass@localhost/mydb"

# Install and launch
pip install mcpdb[web,gemini]
mcpdb web
```

The browser opens automatically with your database already connected. Start asking questions.

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

Each database type requires its driver extra to be installed:

| Database   | Connection String | Install |
|------------|-------------------|---------|
| PostgreSQL | `postgresql://user:pass@host:5432/dbname` | `pip install mcpdb[postgresql]` |
| MySQL      | `mysql://user:pass@host:3306/dbname` | `pip install mcpdb[mysql]` |
| SQLite     | `sqlite:///path/to/database.db` | Built-in |
| SQL Server | `mssql+pyodbc://user:pass@host/dbname?driver=ODBC+Driver+17+for+SQL+Server` | `pip install mcpdb[mssql]` |
| Oracle     | `oracle://user:pass@host:1521/service` | `pip install mcpdb[oracle]` |

### CSV Files

Loaded via the `connect_csv` tool or `load_csv_files` — auto-detects encoding, delimiters, and headers. Multiple CSVs can be loaded into the same DuckDB session for cross-file joins.

### Excel Files

Loaded via the `load_excel` tool. Supports:
- Multi-sheet workbooks
- Automatic table detection vs. text regions
- Formula extraction and explanation
- Cell grid rendering for non-tabular layouts
- Multiple workbooks with cross-workbook references

## Python Sandbox

The agent can execute Python code for data transformations, visualizations, and ML tasks. Code runs in an isolated subprocess with configurable security.

### Default Allowed Libraries

Out of the box, the sandbox allows a broad data science stack:

- **Data**: pandas, numpy, polars, pyarrow, duckdb, sqlalchemy
- **ML/Science**: scikit-learn, torch, xgboost, lightgbm, catboost, scipy
- **Visualization**: matplotlib, seaborn, plotly
- **NLP**: nltk, spacy, transformers
- **Geo/Image**: geopandas, shapely, PIL
- **Standard library**: json, re, math, datetime, collections, itertools, statistics, csv, io, random, hashlib, and more

### Blocked by Default

`os`, `sys`, `subprocess`, `shutil`, `pathlib`, `socket`, `http`, `urllib`, `requests`, `pickle`, `ctypes`, `threading`, `multiprocessing`

### Sandbox Configuration

```yaml
# mcpdb.yaml
sandbox:
  # Add extra modules to the allowlist
  allowed_modules:
    - tensorflow
    - keras
    - networkx

  # Add extra modules to the blocklist
  blocked_modules:
    - some_dangerous_module

  # Allow ALL imports (only blocklist is enforced)
  allow_all: false

  # Resource limits for sandbox subprocess
  memory_mb: 2048
  cpu_seconds: 60
```

**Disable security entirely** (allow everything, block nothing):

```yaml
sandbox:
  allow_all: true
  blocked_modules: []
```

The LLM planner automatically sees which libraries are available and adjusts its code generation accordingly.

## Security

- **Read-only mode** (default): Blocks INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE
- **SQL injection detection**: Flags suspicious patterns (stacked queries, INTO OUTFILE, etc.)
- **Python sandbox**: Subprocess isolation with configurable import allowlist/blocklist, resource limits (memory, CPU)
- **Credential redaction**: Connection strings and API keys are stripped from logs
- **Rate limiting**: Configurable per-session query rate and concurrency limits
- **Circuit breaker**: Automatic backoff on repeated LLM or database failures

## License

MIT
