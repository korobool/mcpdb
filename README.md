# MCPDB — Ask Questions, Get Answers from Any Data

**Version 5.4.0** | [GitHub](https://github.com/korobool/mcpdb) | MIT License

MCPDB is an MCP server and standalone tool for natural language data analysis. Point it at a database, CSV, or Excel file — ask questions in plain English — and get answers with tables, charts, ER diagrams, and exportable Jupyter notebooks.

Supports **PostgreSQL, MySQL, SQLite, SQL Server, Oracle, CSV, and Excel**. Runs standalone via a **web UI**, **CLI**, **REPL**, **TUI**, or as an **MCP server** for any MCP-compatible client.

---

## Web Client

The built-in web client provides a full-featured browser UI with real-time query execution, an execution monitor, and inline chart rendering.

```bash
mcpdb web
```

### Deep Analysis with Charts

The agent automatically generates charts when the question calls for visual analysis. Deep mode runs multiple parallel investigations and synthesizes findings.

![Web UI — Deep mode analysis with bar/line chart and execution monitor](docs/images/web-deep-analysis.png)

### ER Diagram Visualization

Ask about relationships and MCPDB renders interactive ER diagrams using Mermaid, with inferred foreign keys and relationship descriptions.

![Web UI — Entity-relationship diagram with detailed relationship descriptions](docs/images/web-erd-diagram.png)

### Table Overview

Connect a database and immediately see table statistics: row counts, column counts, indexes, and primary keys.

![Web UI — Table details overview](docs/images/web-table-details.png)

### Jupyter Notebook Export

Export any conversation to a Jupyter notebook. The notebook includes setup cells, SQL queries as executable `db_query()` calls, chart code, and markdown commentary — ready to run and modify.

![Exported Jupyter notebook with setup cell and db_query helper](docs/images/web-jupyter-export.png)

---

## CLI Query Mode

Run queries directly from the terminal. Results are formatted with Rich: colored tables, structured output, and mode/timing indicators.

```bash
mcpdb query "mysql+pymysql://user:pass@localhost:3306/mydb" "Show claims frequency by quarter"
```

![CLI query — tabular results with mode indicator and timing](docs/images/cli-query-results.png)

### Jupyter Notebooks with Charts

Exported notebooks contain executable Python code, including matplotlib/seaborn visualizations that reproduce the analysis step by step.

![Jupyter notebook — pie chart generated from exported analysis](docs/images/jupyter-notebook-chart.png)

---

## Installation

### Quick Install

```bash
pip install mcpdb
```

### With Database Drivers

```bash
pip install mcpdb[postgresql]   # PostgreSQL (psycopg2-binary)
pip install mcpdb[mysql]        # MySQL (PyMySQL)
pip install mcpdb[mssql]        # SQL Server (pyodbc)
pip install mcpdb[oracle]       # Oracle (cx_Oracle)
# SQLite is built-in
```

### With All Features

```bash
pip install mcpdb[all]
```

This includes: CSV/Excel support, web client, charts (matplotlib, seaborn), PDF/notebook export, and all LLM providers.

### Development

```bash
git clone https://github.com/korobool/mcpdb.git
cd mcpdb
pip install -e ".[dev,all]"
```

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` | Google Gemini API key (default LLM provider) |
| `OPENAI_API_KEY` | OpenAI API key (alternative provider) |
| `ANTHROPIC_API_KEY` | Anthropic API key (alternative provider) |
| `MCPDB_DATABASE_URL` | Auto-connect database on startup |
| `MCPDB_CONFIG` | Path to `mcpdb.yaml` config file |
| `MCPDB_LOG_LEVEL` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`) |

---

## Usage

### Web Client (Recommended)

```bash
export GEMINI_API_KEY="your-key"
mcpdb web                    # Opens browser automatically
mcpdb web --port 8080        # Custom port
mcpdb web --no-browser       # Start server only
mcpdb web --no-cache         # Skip experience cache lookup
```

Features: database/CSV/Excel connections from the browser, real-time execution pipeline, inline charts, follow-up suggestions, export to HTML/PDF/Jupyter.

### One-Shot Query

```bash
mcpdb query "postgresql://user:pass@host/db" "How many users signed up this month?"
mcpdb query sales.csv "Total revenue by region"
mcpdb query report.xlsx "Average order value per customer"
mcpdb query "sqlite:///app.db" "Show the top 10 products" --no-cache
```

### Interactive REPL

```bash
mcpdb repl "mysql+pymysql://user:pass@host/db"
mcpdb repl data.csv
mcpdb repl financials.xlsx
```

REPL commands: `/help`, `/mode <mode|auto>`, `/schema [table]`, `/history`, `/export <markdown|json>`, `/cache`, `/quit`. Type a number (1, 2, 3) to pick a follow-up suggestion.

### Textual TUI

```bash
pip install mcpdb[tui]
mcpdb tui "postgresql://user:pass@host/db"
```

Windowed terminal UI with source panel, pipeline progress bar, and scrollable result log.

### MCP Server

```bash
mcpdb serve                          # stdio transport (for MCP clients)
mcpdb serve --transport sse          # SSE transport (for web/remote clients)
mcpdb serve --transport sse --port 8765
```

---

## Query Modes

MCPDB automatically classifies each question into the best execution mode:

| Mode | Steps | Use Case | Example |
|------|-------|----------|---------|
| **quick** | 0 | Schema info, metadata | "What tables are in the database?" |
| **simple** | 1–5 | Standard analytical queries | "Top 10 customers by revenue" |
| **extended** | 3–10 | Comprehensive analysis with iterative refinement | "Perform an EDA on the sales table" |
| **optimization** | 1–5 | Large tables (>1M rows), cost-gated | "Analyze all 50M transactions" |
| **deep** | 2–5 investigations | Multi-faceted research, blueprint-based | "Investigate customer churn patterns" |

Override in the REPL: `/mode simple` (or `/mode auto` to reset). In the web UI, select from the dropdown.

---

## MCP Integration Guide

MCPDB implements the [Model Context Protocol](https://modelcontextprotocol.io/) and exposes **33 tools** across 10 categories. Any MCP-compatible client can connect.

### MCP Client Configuration

Any MCP-compatible client (VS Code extensions like Cline/Continue, custom frontends, etc.) can connect using standard MCP configuration:

```json
{
  "mcpServers": {
    "mcpdb": {
      "command": "mcpdb",
      "args": ["serve"],
      "env": {
        "GEMINI_API_KEY": "your-gemini-key"
      }
    }
  }
}
```

For **Cline**, add this to `~/.cline/mcp_settings.json`. For **Continue**, add to your `.continue/config.json` under `mcpServers`.

### SSE Transport (OpenWebUI, Remote Clients)

For clients that connect over HTTP (OpenWebUI, custom web apps, remote integrations):

```bash
# Start the SSE server
mcpdb serve --transport sse --port 8765
```

Connect from the client using the SSE endpoint:
```
http://localhost:8765/sse
```

In **OpenWebUI**, add MCPDB as a tool provider with the SSE URL. The server exposes all 33 tools over the SSE transport, compatible with any MCP client that supports server-sent events.

### Custom Clients (Python, C++, Java, etc.)

MCPDB speaks standard MCP over **stdio** or **SSE**. Any language with an MCP SDK can connect.

#### Python Client

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server_params = StdioServerParameters(
    command="mcpdb",
    args=["serve"],
    env={"GEMINI_API_KEY": "your-key"}
)

async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()

        # List available tools
        tools = await session.list_tools()
        print(f"{len(tools.tools)} tools available")

        # Connect a database
        result = await session.call_tool("connect_database", {
            "connection_string": "sqlite:///mydata.db"
        })

        # Ask a natural language question
        result = await session.call_tool("ask_question", {
            "question": "How many rows in each table?"
        })
        print(result.content[0].text)
```

#### C++ Client

Use the [MCP C++ SDK](https://github.com/modelcontextprotocol/cpp-sdk) to spawn `mcpdb serve` as a subprocess communicating over stdio:

```cpp
#include <mcp/client.h>

int main() {
    // Spawn mcpdb as a child process with stdio transport
    mcp::StdioTransport transport("mcpdb", {"serve"});
    mcp::Client client(transport);
    client.initialize();

    // List tools
    auto tools = client.list_tools();

    // Connect and query
    client.call_tool("connect_database", {
        {"connection_string", "postgresql://user:pass@host/db"}
    });

    auto result = client.call_tool("ask_question", {
        {"question", "What are the top 5 products by sales?"}
    });

    std::cout << result.text() << std::endl;
}
```

#### Java / Kotlin Client

Use the [MCP Java SDK](https://github.com/modelcontextprotocol/java-sdk):

```java
import io.modelcontextprotocol.client.McpClient;
import io.modelcontextprotocol.client.transport.StdioClientTransport;

public class McpdbExample {
    public static void main(String[] args) {
        // Launch mcpdb as subprocess
        var transport = new StdioClientTransport("mcpdb", List.of("serve"));
        var client = McpClient.sync(transport).build();
        client.initialize();

        // Connect to database
        client.callTool("connect_database", Map.of(
            "connection_string", "mysql://user:pass@host/db"
        ));

        // Natural language query
        var result = client.callTool("ask_question", Map.of(
            "question", "Show monthly revenue trends"
        ));
        System.out.println(result.getText());
    }
}
```

#### Any Language (stdio Protocol)

If no MCP SDK exists for your language, communicate directly over stdin/stdout:

1. Spawn `mcpdb serve` as a subprocess
2. Send JSON-RPC 2.0 messages to its stdin
3. Read JSON-RPC 2.0 responses from its stdout

```
→ {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"capabilities":{}}}
← {"jsonrpc":"2.0","id":1,"result":{"capabilities":{"tools":{}}}}

→ {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"connect_database","arguments":{"connection_string":"sqlite:///test.db"}}}
← {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"Connected to test.db (3 tables)"}]}}

→ {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"ask_question","arguments":{"question":"How many rows in each table?"}}}
← {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"...results..."}]}}
```

The protocol is [JSON-RPC 2.0](https://www.jsonrpc.org/specification) with messages delimited by newlines. See the [MCP specification](https://spec.modelcontextprotocol.io/) for the full protocol reference.

---

## MCP Tools Reference

MCPDB exposes 33 tools organized into 10 categories:

### Session Management
| Tool | Description |
|------|-------------|
| `connect_database` | Connect to SQL databases (PostgreSQL, MySQL, SQLite, SQL Server, Oracle) |
| `load_csv_files` | Load CSV files with auto-detection of encoding, delimiters, headers |
| `list_sources` | List all connected data sources |
| `remove_source` | Disconnect a data source |
| `get_source_schema` | Get full schema description of a data source |
| `get_session_status` | Get current session status including active sources and metadata |

### Querying
| Tool | Description |
|------|-------------|
| `execute_sql` | Execute SQL queries on connected data sources |
| `get_table_sample` | Get sample rows from a table |
| `validate_sql` | Check SQL syntax without executing |
| `cross_source_query` | Execute SQL spanning multiple sources with DuckDB federation |

### Discovery
| Tool | Description |
|------|-------------|
| `search_schema` | Search tables and columns by keyword |
| `explain_query` | Show EXPLAIN plan for SQL queries |
| `render_erd` | Generate Mermaid ER diagrams |

### Profiling
| Tool | Description |
|------|-------------|
| `profile_table` | Table statistics: row count, nulls, distinct values, min/max, indexes |
| `profile_column` | Column profiling: data type, top values, distribution |

### Relationships
| Tool | Description |
|------|-------------|
| `find_relationships` | Discover relationships (explicit FKs + inferred joins) |
| `suggest_joins` | Suggest JOIN conditions based on FK and column relationships |

### Excel
| Tool | Description |
|------|-------------|
| `load_excel` | Load Excel workbooks with automatic table detection |
| `list_sheets` | List sheets with structure info |
| `read_range` | Read cell ranges (e.g., `A1:D10`) |
| `extract_excel_table` | Extract rectangular regions as tables |
| `explain_formula` | Explain Excel formulas in natural language |

### Analysis
| Tool | Description |
|------|-------------|
| `ask_question` | Natural language questions — agent classifies, plans, executes, synthesizes |
| `suggest_followups` | Generate 3–5 context-aware follow-up questions |

### Export
| Tool | Description |
|------|-------------|
| `export_conversation` | Export to HTML, PDF, or Jupyter notebook |

### Experience Management
| Tool | Description |
|------|-------------|
| `get_experience_stats` | Cache hit statistics and learned patterns |
| `list_cached_queries` | List cached queries for a source |
| `invalidate_cache_entry` | Invalidate specific cached responses |
| `clear_experience` | Clear all experience data for a source |
| `vote_response` | Vote on response quality (positive/negative) |

### Execution Control
| Tool | Description |
|------|-------------|
| `cancel_execution` | Cancel in-progress agent execution |
| `add_context` | Add context or instructions to a running execution |
| `submit_strategy` | Submit strategy for expensive queries (SAMPLE, FULL, CANCEL) |

---

## Docker

The Docker image ships all modes (web, query, repl, tui, serve) and most database drivers pre-installed.

### Quick Start

```bash
# Build the image
docker build -t mcpdb .

# Run web client (default) — opens on http://localhost:8080
docker run --rm -p 8080:8080 -e GEMINI_API_KEY=your-key mcpdb
```

### Docker Compose

```bash
export GEMINI_API_KEY=your-key
docker compose up -d        # Start in background
docker compose logs -f      # Follow logs
docker compose down          # Stop
```

Edit `docker-compose.yml` to add database URLs, mount config files, or switch LLM providers.

### All CLI Modes

Every mode works inside the container, not just web:

```bash
# One-shot query against a remote database
docker run --rm -e GEMINI_API_KEY=your-key mcpdb \
  mcpdb query "postgresql://user:pass@host/db" "How many customers?"

# Query a local CSV file (mount it into the container)
docker run --rm -e GEMINI_API_KEY=your-key -v /path/to/data:/data mcpdb \
  mcpdb query /data/sales.csv "Top 10 products by revenue"

# Interactive REPL
docker run --rm -it -e GEMINI_API_KEY=your-key mcpdb \
  mcpdb repl "mysql+pymysql://user:pass@host/db"

# Textual TUI
docker run --rm -it -e GEMINI_API_KEY=your-key mcpdb \
  mcpdb tui "sqlite:///data/my.db"

# MCP server (SSE transport for remote clients)
docker run --rm -p 8765:8765 -e GEMINI_API_KEY=your-key mcpdb \
  mcpdb serve --transport sse --port 8765
```

### Connecting to Host Databases

To reach databases running on the host machine:

```bash
# Linux: use --network host
docker run --rm --network host -e GEMINI_API_KEY=your-key mcpdb \
  mcpdb query "mysql+pymysql://user:pass@localhost:3306/db" "Show tables"

# macOS / Windows: use host.docker.internal
docker run --rm -e GEMINI_API_KEY=your-key mcpdb \
  mcpdb query "postgresql://user:pass@host.docker.internal:5432/db" "Show tables"
```

### Persistent Data

Mount a volume to keep the experience cache and exported charts across restarts:

```bash
docker run --rm -p 8080:8080 -e GEMINI_API_KEY=your-key \
  -v mcpdb-data:/data mcpdb
```

### API Keys and Secrets

MCPDB resolves API keys in priority order:

1. **Explicit value** — passed in config or code
2. **Environment variable** — `GEMINI_API_KEY=xxx`
3. **File-based secret** (`_FILE` suffix) — `GEMINI_API_KEY_FILE=/run/secrets/gemini_key`
4. **`.env` file** — loaded automatically if `python-dotenv` is installed

The `_FILE` convention is the Docker/Kubernetes standard — the value is read from the file at that path. This works with Docker secrets, Kubernetes secrets mounted as volumes, and manual file mounts.

```bash
# Environment variable (simplest)
docker run --rm -p 8080:8080 -e GEMINI_API_KEY=your-key mcpdb

# File-based secret (production)
echo "your-key" > ./secrets/gemini_key.txt
docker run --rm -p 8080:8080 \
  -v ./secrets:/run/secrets:ro \
  -e GEMINI_API_KEY_FILE=/run/secrets/gemini_key.txt \
  mcpdb

# Docker Swarm secrets
docker secret create gemini_key ./secrets/gemini_key.txt
# Then in docker-compose.yml, reference the secret (see comments in file)

# .env file (local development)
cp .env.example .env    # Edit with your keys
mcpdb web               # Keys loaded automatically
```

### Custom Configuration

Mount a `mcpdb.yaml` (see `mcpdb.yaml.example` for all options):

```bash
docker run --rm -p 8080:8080 -e GEMINI_API_KEY=your-key \
  -v ./mcpdb.yaml:/app/mcpdb.yaml:ro mcpdb
```

---

## Configuration

MCPDB looks for `mcpdb.yaml` in: `$MCPDB_CONFIG` → `./mcpdb.yaml` → built-in defaults.

```yaml
llm:
  reasoning:
    provider: gemini          # gemini | openai | anthropic | ollama
    model: gemini-2.5-pro     # Model name
    api_key: ${GEMINI_API_KEY}

server:
  transport: stdio            # stdio | sse
  host: 0.0.0.0
  port: 8765

execution:
  query_timeout: 600          # SQL query timeout (seconds)
  python_timeout: 30          # Sandbox execution timeout
  max_rows: 10000             # Maximum rows returned

experience:
  storage_dir: ~/.mcpdb/experience
  max_age_days: 30
```

Environment variables are expanded with `${VAR_NAME}` syntax.

---

## Architecture

```
mcpdb/
├── mcp/                    MCP protocol layer (33 tools, resources, prompts)
│   ├── server.py           Server creation + stdio/SSE transport
│   └── tools/              Tool implementations across 10 categories
├── agent/                  Agent orchestration (custom graph)
│   ├── graph.py            Main graph: classify → mode → synthesize
│   ├── nodes/              Plan, execute, debug, synthesize, validate
│   ├── subgraphs/          Mode-specific: quick, simple, extended, optimization, deep
│   └── observer.py         Async execution monitoring + cancellation
├── sources/                Data source abstraction
│   ├── database/           SQL databases (5 dialects)
│   ├── csv/                CSV → DuckDB
│   └── excel/              Excel workbooks
├── llm/                    LLM provider abstraction
│   ├── factory.py          create_provider() — Gemini, OpenAI, Anthropic, Ollama
│   └── provider.py         Base class + JSON extraction/repair
├── sandbox/                Secure Python execution (subprocess-based)
├── security/               SQL safety, credential redaction, rate limiting
├── experience/             Two-tier cache (exact + semantic), quality evaluation
├── web/                    FastAPI + WebSocket web client
│   ├── app.py              REST + WebSocket + 20+ event types
│   ├── export.py           HTML/PDF/notebook generation
│   └── templates/          Single-page HTML (CSS + JS inline)
└── cli/                    Rich terminal UI, REPL, Textual TUI
```

### Key Design Decisions

- **Single MCP dispatcher** — one `list_tools`/`call_tool` pair routes to all 33 tools
- **LLM-agnostic** — pluggable providers (Gemini default, OpenAI/Anthropic/Ollama alternatives)
- **Safe by default** — SQL is read-only enforced, Python runs in a subprocess sandbox, credentials are redacted in logs
- **5 thinking modes** — from instant schema lookups (quick) to multi-investigation research (deep)
- **Experience learning** — successful queries cached with exact + semantic matching, mode-aware filtering, automatic schema drift detection

---

## Supported Data Sources

| Source | Connection Format | Notes |
|--------|------------------|-------|
| PostgreSQL | `postgresql://user:pass@host:5432/db` | Requires `psycopg2-binary` |
| MySQL | `mysql+pymysql://user:pass@host:3306/db` | Requires `PyMySQL` |
| SQLite | `sqlite:///path/to/file.db` | Built-in, no extra driver |
| SQL Server | `mssql+pyodbc://user:pass@host/db?driver=ODBC+Driver+17+for+SQL+Server` | Requires `pyodbc` |
| Oracle | `oracle://user:pass@host:1521/service` | Requires `cx_Oracle` |
| CSV | `data.csv` or `a.csv,b.csv` | Auto-detects encoding, delimiters |
| Excel | `report.xlsx` | Dual mode: queryable tables + spreadsheet operations |

---

## Export Formats

From the web client, export any conversation:

| Format | Description |
|--------|-------------|
| **HTML** | Self-contained single-file report with styling, tables, and embedded chart images |
| **PDF** | Downloadable PDF document with full conversation |
| **Jupyter Notebook** | `.ipynb` with setup cell, executable `db_query()` calls, chart code, and ERD diagrams |

CSV and Excel sources export as data-focused notebooks with pandas DataFrames.

---

## Further Reading

- [Development & Configuration Guide](docs/DEVELOPMENT.md) — LLM providers, sandbox security, YAML config reference, debugging, testing, architecture

## License

MIT
