# MCPDB — Development & Configuration Guide

> For an overview, screenshots, and MCP integration examples, see the main [README](../README.md).

This document covers configuration, LLM providers, sandbox security, debugging, testing, and architecture details for developers and operators.

## Development Setup

```bash
git clone https://github.com/korobool/mcpdb.git
cd mcpdb
pip install -e ".[dev,all]"
```

Requires Python 3.10+.

## Configuration

MCPDB loads configuration from YAML. Search order:

1. Explicit path via `MCPDB_CONFIG` environment variable
2. `./mcpdb.yaml` in the current directory
3. Built-in defaults (no file needed)

### Full `mcpdb.yaml` Reference

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

## LLM Providers

### Google Gemini (Default)

1. Get an API key from [Google AI Studio](https://aistudio.google.com/apikey).
2. Install: `pip install mcpdb[gemini]`
3. Set: `export GEMINI_API_KEY="your-key-here"`

Customize in `mcpdb.yaml`:
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

For Claude Desktop, pass the key in MCP config:
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

### OpenAI

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

### Ollama (Local Models)

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

## Python Sandbox

The agent executes Python code for data transformations, visualizations, and ML tasks. Code runs in an isolated subprocess with configurable security.

### Default Allowed Libraries

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

## Debugging

### Logging

MCPDB logs to stderr. Control verbosity with `MCPDB_LOG_LEVEL`:

```bash
# Debug — shows all LLM calls, SQL execution, agent state transitions
MCPDB_LOG_LEVEL=DEBUG mcpdb serve

# Warning only
MCPDB_LOG_LEVEL=WARNING mcpdb serve
```

Log format: `2025-01-15 10:30:45 [DEBUG] mcpdb.agent.graph: classify → simple mode`

### Debugging the Agent

Trace agent execution step by step:

```bash
MCPDB_LOG_LEVEL=DEBUG mcpdb query "sqlite:///test.db" "How many rows in users?"
```

This prints: classification result, planning output, each execution step with timing, synthesis and final response.

### Debugging MCP Communication

```bash
# Use the MCP Inspector tool
npx @modelcontextprotocol/inspector mcpdb serve
```

### Running as a Background Service

```bash
nohup mcpdb serve --transport sse --port 8765 > mcpdb.log 2>&1 &
# Stop with: kill $(pgrep -f "mcpdb serve")
```

## Testing

```bash
# Run all tests (1000+ test suite)
python -m pytest

# Run a specific test file
python -m pytest tests/test_agent.py

# Run with verbose output
python -m pytest -v

# Run tests matching a pattern
python -m pytest -k "test_cost"

# Quick feedback during development
python -m pytest --tb=short -q
```

Tests use pytest with `pytest-asyncio` for async code. Unit tests use SQLite (no external DB needed).

## Architecture

```
mcpdb/
├── __main__.py          # CLI entry point
├── config.py            # YAML config loader with env var resolution
├── agent/               # LangGraph agent orchestration
│   ├── graph.py         # Main agent graph (classify → mode → synthesize)
│   ├── state.py         # AgentState TypedDict
│   ├── nodes/           # Plan, execute, debug, synthesize, validate
│   ├── subgraphs/       # quick, simple, extended, optimization, deep
│   ├── observer.py      # Async execution monitoring + cancellation
│   └── cancellation.py  # CancellationToken, mid-execution abort
├── sources/             # Data source abstraction layer
│   ├── base.py          # DataSource, QueryableSource, SpreadsheetSource ABCs
│   ├── registry.py      # SourceRegistry (add/remove/get sources)
│   ├── database/        # SQL databases (5 dialects)
│   ├── csv/             # CSV → DuckDB
│   └── excel/           # Excel workbooks (multi-sheet, formula analysis)
├── mcp/                 # MCP protocol layer
│   ├── server.py        # Server creation + stdio/SSE transport
│   ├── resources.py     # MCP resources (schema://, erd://, session://)
│   ├── prompts.py       # MCP prompts (explore_source, deep_table_analysis)
│   └── tools/           # 33 MCP tools across 10 categories
├── llm/                 # LLM provider abstraction
│   ├── provider.py      # LLMProvider ABC, _extract_json(), _repair_json()
│   ├── factory.py       # create_provider() factory
│   ├── gemini_provider.py, openai_provider.py
│   ├── anthropic_provider.py, ollama_provider.py
├── sandbox/             # Secure Python execution (subprocess-based)
├── security/            # SQL safety, credential redaction, rate limiting
├── experience/          # Two-tier cache, quality evaluation, anti-patterns
├── web/                 # FastAPI + WebSocket web client
│   ├── app.py           # REST + WebSocket + 20+ event types
│   ├── export.py        # HTML/PDF/notebook generation
│   └── templates/       # Single-page HTML (CSS + JS inline)
└── cli/                 # Rich terminal UI, REPL, Textual TUI
```

### Key Design Decisions

- **Single MCP dispatcher** — one `list_tools`/`call_tool` pair routes to all 33 tools
- **LLM-agnostic** — pluggable providers via `create_provider(provider, model, api_key)`
- **Safe by default** — read-only SQL, subprocess sandbox, credential redaction
- **5 thinking modes** — auto-classified per question (quick → simple → extended → optimization → deep)
- **Experience learning** — exact + semantic cache, mode-aware filtering, schema drift detection
- **No build step** — web client is pure HTML/CSS/JS served by FastAPI, no npm/webpack

## License

MIT
