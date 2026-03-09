# MCPDB Technical Specification

**Version 5.3.0** | Last updated: 2026-03-09

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [Data Source Abstraction Layer](#3-data-source-abstraction-layer)
4. [Database Source](#4-database-source)
5. [CSV Source](#5-csv-source)
6. [Excel Source](#6-excel-source)
7. [Source Registry & Federation](#7-source-registry--federation)
8. [LangGraph Agent Orchestration](#8-langgraph-agent-orchestration)
9. [Agent Nodes](#9-agent-nodes)
10. [Five Thinking Modes](#10-five-thinking-modes)
11. [Async Reasoning Observer](#11-async-reasoning-observer)
12. [Experience & Learning System](#12-experience--learning-system)
13. [LLM Integration Layer](#13-llm-integration-layer)
14. [Python Execution Sandbox](#14-python-execution-sandbox)
15. [Security](#15-security)
16. [MCP Server — Tools, Resources & Prompts](#16-mcp-server--tools-resources--prompts)
17. [Web Client](#17-web-client)
18. [CLI, REPL & TUI](#18-cli-repl--tui)
19. [Export System](#19-export-system)
20. [Configuration](#20-configuration)
21. [Data Models & Type Contracts](#21-data-models--type-contracts)
22. [Error Handling](#22-error-handling)
23. [Testing](#23-testing)
24. [Project Structure](#24-project-structure)

---

## 1. System Overview

MCPDB is a production-grade agentic system that enables natural language interaction with **databases**, **CSV files**, and **Excel workbooks**. It is built as a **LangGraph-based agent** exposed through the **Model Context Protocol (MCP)**, making it usable from any MCP-compatible client (VS Code extensions, custom frontends, etc.).

### 1.1 Functional Capabilities

1. **Natural language querying** of databases (PostgreSQL, MySQL, SQLite, SQL Server, Oracle)
2. **Natural language analysis** of CSV files (single and multi-file, with cross-file joins via DuckDB)
3. **Natural language exploration** of Excel workbooks (formulas, non-rectangular data, multi-sheet)
4. **Mixed-source analysis** — join/combine data across databases, CSVs, and Excel files
5. **Intelligent query routing** — auto-classify questions into 5 execution modes (quick / simple / extended / optimization / deep)
6. **Self-healing execution** — auto-detect and fix errors via LLM-assisted debugging (up to 3 retries)
7. **Rich output** — tables, charts (matplotlib/seaborn), Mermaid ER diagrams, markdown
8. **Cost-aware execution** — EXPLAIN-based cost estimation, strategy gate for large tables
9. **Experience learning** — two-tier cache (exact + semantic), anti-pattern tracking, quality evaluation
10. **Export** — HTML reports, PDF documents, Jupyter notebooks with executable code

### 1.2 Design Principles

- **MCP-first** — all capabilities exposed as 33 MCP tools; every UI is just a client
- **Provider-agnostic** — pluggable LLM providers (Gemini default, OpenAI, Anthropic, Ollama)
- **Safe by default** — read-only SQL, subprocess sandbox, credential redaction
- **No build step** — web client is pure HTML/CSS/JS served by FastAPI
- **Extensible** — adding a new data source requires implementing one ABC

### 1.3 Non-Goals

- Real-time streaming data (Kafka, etc.)
- Data modification (INSERT/UPDATE/DELETE) — read-only by default
- Database administration (schema changes, user management)
- ETL pipelines or scheduled jobs

---

## 2. Architecture

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           MCP CLIENTS                               │
│  ┌──────────┐  ┌──────────────┐  ┌─────┐  ┌────────────────────┐   │
│  ┌──────────┐  ┌──────────────┐  ┌─────┐  ┌────────────────────┐   │
│  │ VS Code /│  │ Custom MCP   │  │ CLI │  │ MCPDB Web Client   │   │
│  │ IDE ext  │  │ clients      │  │     │  │ (FastAPI+WebSocket) │   │
│  └────┬─────┘  └──────┬───────┘  └──┬──┘  └────────┬───────────┘   │
│       │               │             │               │               │
│       └───────────────┴──────┬──────┴───────────────┘               │
│                              │                                      │
│                     ┌────────┴────────┐                             │
│                     │   MCP Protocol  │  stdio / SSE               │
│                     │   (JSON-RPC)    │  SSE (web/remote clients)   │
│                     └────────┬────────┘                             │
└──────────────────────────────┼──────────────────────────────────────┘
                               │
┌──────────────────────────────┼──────────────────────────────────────┐
│                     MCPDB SERVER                                    │
│                              │                                      │
│              ┌───────────────┴───────────────┐                      │
│              │       MCP Tool Dispatcher      │  33 tools           │
│              │    (register_all_tools)         │  10 categories      │
│              └───────────┬───────────────────┘                      │
│                          │                                          │
│    ┌─────────────────────┼─────────────────────┐                    │
│    │              Agent Orchestrator            │                    │
│    │           (LangGraph state machine)        │                    │
│    │                                            │                    │
│    │  classify → route → [mode subgraph] → out  │                    │
│    │                                            │                    │
│    │  Modes: quick│simple│extended│optim│deep    │                    │
│    └──────┬───────────────┬────────────┬────────┘                    │
│           │               │            │                            │
│    ┌──────┴──────┐ ┌──────┴─────┐ ┌────┴────┐                      │
│    │ LLM Layer   │ │  Sandbox   │ │Experience│                      │
│    │ (4 providers)│ │ (subprocess│ │ Cache    │                      │
│    │             │ │  isolation) │ │ + Staging│                      │
│    └─────────────┘ └────────────┘ └─────────┘                      │
│           │                                                         │
│    ┌──────┴───────────────────────────────────┐                     │
│    │          Source Registry                   │                    │
│    │  ┌──────────┐ ┌────────┐ ┌────────────┐  │                    │
│    │  │ Database  │ │  CSV   │ │   Excel    │  │                    │
│    │  │ (5 dials) │ │(DuckDB)│ │(dual mode) │  │                    │
│    │  └──────────┘ └────────┘ └────────────┘  │                    │
│    └──────────────────────────────────────────┘                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Key Subsystems

| Subsystem | Package | Responsibility |
|-----------|---------|---------------|
| Sources | `mcpdb/sources/` | Data source abstraction, connection, schema introspection |
| Agent | `mcpdb/agent/` | LangGraph orchestration, mode routing, plan/execute/synthesize |
| LLM | `mcpdb/llm/` | Provider abstraction, JSON extraction, fallback chain |
| Sandbox | `mcpdb/sandbox/` | Secure Python execution with resource limits |
| Security | `mcpdb/security/` | SQL safety, credential redaction, rate limiting |
| Experience | `mcpdb/experience/` | Caching, staging, quality evaluation, anti-patterns |
| MCP | `mcpdb/mcp/` | Tool registration, resource templates, prompt definitions |
| Web | `mcpdb/web/` | FastAPI + WebSocket web client, export engine |
| CLI | `mcpdb/cli/` | Rich terminal output, REPL, Textual TUI |
| Config | `mcpdb/config.py` | YAML loading with env var resolution |

### 2.3 Data Flow

A natural language question flows through the system as follows:

```
Question → Classify (LLM) → Mode Route → Plan (LLM) → Execute (SQL/Python)
    ↕              ↕              ↕            ↕              ↕
  Cache        Observer      Callbacks      Anti-        Sandbox
  Lookup       (timing)      (events)      patterns     (isolation)
                                              ↕
                                         Debug (LLM)
                                              ↕
                                       Validate → Replan?
                                              ↕
                                    Synthesize (LLM) → Response
```

---

## 3. Data Source Abstraction Layer

**Package:** `mcpdb/sources/base.py`

### 3.1 Type Hierarchy

```
DataSource (ABC)
├── QueryableSource (ABC)     — SQL-queryable sources
│   ├── DatabaseSource        — SQL databases (5 dialects)
│   ├── CsvSource             — CSV files via DuckDB
│   └── ExcelSource           — Excel tables via DuckDB
└── SpreadsheetSource (ABC)   — Spreadsheet operations
    └── ExcelSource           — Cell ranges, formulas, structure
```

ExcelSource implements **both** `QueryableSource` and `SpreadsheetSource`, providing dual-mode access.

### 3.2 Core ABCs

```python
class DataSource(ABC):
    """Base for all data sources."""
    @abstractmethod
    def get_metadata(self) -> SourceMetadata: ...
    @abstractmethod
    def get_context_description(self) -> str: ...
    @abstractmethod
    def close(self) -> None: ...
    @property
    @abstractmethod
    def source_type(self) -> SourceType: ...

    # Concrete methods
    def get_schema_json(self) -> str: ...
    def get_tables(self) -> list[TableInfo]: ...
    def get_relationships(self) -> list[dict]: ...

class QueryableSource(DataSource):
    """Sources that support SQL queries."""
    @abstractmethod
    def execute_query(self, query: str, max_rows: int = 100) -> pd.DataFrame: ...
    @abstractmethod
    def get_sample(self, table_name: str, limit: int = 5) -> pd.DataFrame: ...

class SpreadsheetSource(DataSource):
    """Sources with spreadsheet-specific operations."""
    @abstractmethod
    def list_sheets(self) -> list[dict]: ...
    @abstractmethod
    def read_range(self, sheet: str, range_str: str | None = None,
                   include_formulas: bool = False) -> Any: ...
    @abstractmethod
    def get_sheet_structure(self, sheet: str) -> Any: ...
    @abstractmethod
    def extract_table(self, sheet: str, table_range: str) -> pd.DataFrame: ...
```

### 3.3 Data Types

```python
class SourceType(Enum):
    DATABASE = "database"
    CSV = "csv"
    EXCEL = "excel"

@dataclass
class ColumnInfo:
    name: str
    dtype: str
    nullable: bool
    description: str = ""

@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo]
    row_count: int | None = None
    schema: str | None = None
    source_file: str | None = None
    sheet_name: str | None = None
    primary_keys: list[str] = field(default_factory=list)
    indexes: list[dict] = field(default_factory=list)

@dataclass
class SourceMetadata:
    source_id: str
    source_type: SourceType
    display_name: str
    tables: list[TableInfo]
    capabilities: list[str]
    raw_info: dict[str, Any] = field(default_factory=dict)
```

---

## 4. Database Source

**Package:** `mcpdb/sources/database/`

### 4.1 DatabaseSource

`DatabaseSource(QueryableSource)` wraps a SQL database via SQLAlchemy.

**Constructor:**
```python
DatabaseSource(
    connection_string: str,
    display_name: str | None = None,
    connect_timeout: int = 10,
    query_timeout: int = 30
)
```

**Supported dialects:** PostgreSQL, MySQL, SQLite, SQL Server, Oracle

**Key behavior:**
- Source ID generated via MD5 hash of connection string (`host_db_hash` format)
- Connection string passwords redacted in metadata and logs
- Foreign keys extracted via SQLAlchemy inspector
- Tables classified by size: SMALL (<10K), MEDIUM (10K-100K), LARGE (100K-1M), VERY_LARGE (>1M)

### 4.2 DatabaseConnector

Low-level connection management:

- SQLAlchemy engine with configurable pool size (default 5)
- `execute_query()` sets `mcpdb_truncated` and `mcpdb_total_rows` attributes on returned DataFrames
- `@retry_on_connection_error` decorator with exponential backoff (3 retries)
- `get_schemas()` filters out system schemas (information_schema, pg_catalog, etc.)

### 4.3 SchemaExplorer

Introspects database structure:

- Bulk row counts via dialect-specific queries
- Per-table exploration: columns, data types, primary keys, foreign keys, indexes
- `TableSizeTag` enum for cost-gate thresholds
- Results cached as `list[TableInfo]`

### 4.4 Dialect System

Each dialect (`mcpdb/sources/database/dialects/`) provides:
- SQL generation for bulk row counts
- Identifier quoting rules
- System schema filtering
- Data type normalization

---

## 5. CSV Source

**Package:** `mcpdb/sources/csv/`

### 5.1 CsvSource

`CsvSource(QueryableSource)` loads CSV/TSV files into DuckDB for SQL querying.

**Constructor:**
```python
CsvSource(
    file_paths: list[str] | str,
    display_name: str | None = None,
    memory_limit: str = "2GB",
    table_names: list[str] | None = None
)
```

### 5.2 Processing Pipeline

1. **Detection** — `detect_csv()` auto-detects encoding (chardet), delimiter (csv.Sniffer with manual fallback), and header presence
2. **Loading** — each CSV loaded into DuckDB as a named table via `DuckDBBackend.load_csv()`
3. **Introspection** — column info extracted from DuckDB schema
4. **Querying** — standard SQL executed against DuckDB

**CsvLoadResult** captures: table_name, file_path, encoding, delimiter, has_header, row_count, column_count, columns.

### 5.3 DuckDB Backend

- In-process DuckDB instance per CsvSource
- Configurable memory limit and thread count
- PostgreSQL-compatible SQL dialect
- Multiple CSVs in one session enable cross-file JOINs

---

## 6. Excel Source

**Package:** `mcpdb/sources/excel/`

### 6.1 Dual-Mode Architecture

`ExcelSource(QueryableSource, SpreadsheetSource)` provides two interfaces:

1. **QueryableSource** — detected tables loaded into DuckDB for SQL queries
2. **SpreadsheetSource** — cell-level access, formula inspection, structure analysis

This dual mode means an Excel workbook can be queried with SQL (for tabular data) and inspected as a spreadsheet (for formulas, merged cells, non-rectangular layouts).

### 6.2 Table Detection

The `StructureAnalyzer` scans each sheet:

- Identifies rectangular tabular regions (consistent column types, header row)
- Distinguishes tables from text regions, summary blocks, charts
- Handles merged cells and multi-header layouts
- Each detected table gets a DuckDB-queryable name: `{sheet}_{table_index}`

### 6.3 Formula Intelligence

- `WorkbookReader` (openpyxl) extracts cell values and formulas
- `FormulaDependencyGraph` traces formula references across cells and sheets
- `FormulaClusters` groups structurally similar formulas (e.g., column totals)
- Formula analysis results cached per sheet

### 6.4 Context Enrichment

`get_context_description()` builds a rich LLM context including:
- Sheet overview (table count, text region count per sheet)
- Queryable tables with column names and row counts
- Text regions with content previews
- Formula intelligence: clusters, dependency highlights
- This helps the LLM decide whether to use SQL or spreadsheet operations

---

## 7. Source Registry & Federation

**File:** `mcpdb/sources/registry.py`

### 7.1 SourceRegistry

Thread-safe container for active data sources.

```python
class SourceRegistry:
    def add_source(self, source: DataSource) -> str: ...
    def remove_source(self, source_id: str) -> None: ...
    def get_source(self, source_id: str) -> DataSource: ...
    def list_sources(self) -> list[SourceMetadata]: ...
    def get_combined_context(self) -> str: ...
    def get_queryable_sources(self) -> list[QueryableSource]: ...
    def get_spreadsheet_sources(self) -> list[SpreadsheetSource]: ...
    def close_all(self) -> None: ...
```

- `add_source()` returns the source_id (auto-generated from source content)
- `get_combined_context()` aggregates schema descriptions from all sources into a single string for LLM prompts
- Raises `SourceNotFoundError` (subclass of `KeyError`) for missing sources
- Thread safety via `threading.Lock()`

### 7.2 Cross-Source Federation

**File:** `mcpdb/sources/federation.py`

The `cross_source_query` tool enables SQL across multiple sources:

1. Fetch required tables from different sources into DuckDB
2. Execute the federated SQL against the unified DuckDB session
3. Return the combined result as a DataFrame

---

## 8. LangGraph Agent Orchestration

**Package:** `mcpdb/agent/`

### 8.1 Entry Point

```python
async def run_agent(
    question: str,
    registry: SourceRegistry,
    llm: LLMProvider,
    callbacks: CallbackManager | None = None,
    mode_override: str | None = None,
    experience_cache: ExperienceCache | None = None,
    force_rethink: bool = False,
    staging_store: StagingStore | None = None,
    no_cache: bool = False,
    cancellation_token: CancellationToken | None = None,
    enable_observer: bool = True,
) -> AgentState:
```

### 8.2 Execution Flow

```
1. Build initial state (question, source_context, active_source_ids)
2. Inject anti-pattern context from experience data
3. Check experience cache
   ├── Cache hit → replay cached code against live data → return
   └── Cache miss → continue
4. Start AsyncReasoningObserver
5. Classify question → mode
6. Route to mode subgraph:
   ├── quick   → context-only answer (may escalate to simple)
   ├── simple  → plan → execute → validate → synthesize
   ├── extended → plan → execute with checkpoints → reflect → synthesize
   ├── optimization → plan → cost check → strategy gate → execute → synthesize
   └── deep    → blueprint → parallel investigations → synthesize report
7. Record anti-patterns from failures
8. Stage result for quality evaluation
9. Stop observer, return AgentState
```

### 8.3 Cache Semantics

| Flag | Lookup | Populate | Invalidate |
|------|--------|----------|------------|
| (default) | Yes | Yes | No |
| `no_cache=True` | Skip | Yes | No |
| `force_rethink=True` | Skip | Yes | Yes (old entry) |

Quick-mode responses with no executable steps are auto-promoted to cache (skip staging).

### 8.4 AgentState

```python
class AgentState(TypedDict, total=False):
    # Input
    question: str
    source_context: str
    active_source_ids: list[str]

    # Classification
    query_mode: str              # quick | simple | extended | optimization_required | deep
    target_sources: list[str]
    requires_cross_source: bool
    key_entities: list[str]

    # Quick mode
    answer: str

    # Planning & execution
    plan: dict                   # {analysis, approach, steps[]}
    execution_log: list[dict]
    artifacts: list[dict]        # tables, charts, cell grids
    last_result: str             # preview of last step result

    # Debugging
    max_retries: int
    current_error: str

    # Cost gate
    optimization_state: str
    cost_analysis: dict
    strategy_choice: str         # SAMPLE | FULL | CANCEL

    # Validation
    validation_result: str       # adequate | inadequate | needs_data
    validation_reason: str
    replan_count: int

    # Extended mode
    checkpoint_results: list[dict]
    checkpoint_action: str
    reflection: str

    # Experience
    cache_hit: bool
    cached_response: str

    # Observer
    observer_report: dict
    cancellation_token: CancellationToken

    # Output
    response: str
```

### 8.5 Callback System

`CallbackManager` dispatches events during execution:

| Event | When | Data |
|-------|------|------|
| `on_classify_start` | Before classification | question |
| `on_classify_complete` | After classification | mode, reasoning |
| `on_plan_start` | Before planning | mode |
| `on_plan_ready` | After planning | step count, descriptions |
| `on_step_start` | Before each execution step | step number, action, code |
| `on_step_complete` | After each step | result preview, timing |
| `on_step_error` | On step failure | error message, attempt count |
| `on_debug_start` | Before debug attempt | error, attempt |
| `on_debug_complete` | After debug fix | fixed code |
| `on_synthesize_start` | Before synthesis | - |
| `on_synthesize_complete` | After synthesis | response text |
| `on_chart` | Chart generated in sandbox | base64 PNG |
| `on_deep_investigation` | Deep mode investigation complete | investigation result |

---

## 9. Agent Nodes

**Package:** `mcpdb/agent/nodes/`

### 9.1 Classification (`classify.py`)

Determines the execution mode for a question.

**Fast-path patterns** (skip LLM call):
- Mermaid/ERD/diagram requests → quick
- Schema/structure questions → quick
- FK/PK/relationship questions → quick

**LLM classification** returns:
```json
{
    "mode": "quick|simple|extended|optimization_required|deep",
    "reasoning": "Why this mode",
    "target_sources": ["source_id_1"],
    "requires_cross_source": false,
    "key_entities": ["table_name", "column_name"]
}
```

Fallback: defaults to `simple` mode on LLM failure after 3 retries.

### 9.2 Planning (`common.py`)

**3-tier retry strategy:**
1. Full prompt with source context and experience data
2. Simpler prompt (reduced context)
3. Hardcoded fallback plan (basic schema exploration)

**Plan schema:**
```json
{
    "analysis": "What the user wants",
    "approach": "How we'll get it",
    "steps": [
        {
            "step_number": 1,
            "action": "sql|python|schema|sample",
            "source_id": "source_id",
            "description": "What this step does",
            "code": "SELECT ... or import matplotlib...",
            "status": "pending",
            "attempts": 0
        }
    ]
}
```

**Critical planning rules enforced via prompt:**
- `df` variable contains ONLY the result from the immediately preceding SQL step
- Cannot reference earlier step results (stateless between steps)
- MySQL-specific: use `ROW_NUMBER()` for median, avoid `PERCENTILE_CONT`
- NULLs: always handle with `IS NOT NULL` filters
- Ratios: use `NULLIF()` to avoid division by zero
- EDA mode: include diverse chart types with `plt.show()`

### 9.3 Execution (`common.py`)

Steps are executed sequentially:

- **sql** → `QueryableSource.execute_query()` (read-only validated)
- **python** → Sandbox subprocess with `df` from preceding step, captures charts
- **schema** → `DataSource.get_context_description()`
- **sample** → `QueryableSource.get_sample()`

On failure → debug node (LLM analyzes error, produces fixed code) → retry (max 3 attempts). Debug node advances past the step on final failure to prevent infinite loops.

### 9.4 Synthesis (`common.py`)

LLM synthesizes a natural language response from:
- Original question
- Plan with step descriptions
- Execution results (DataFrames, charts, errors)
- Source context

**Fast-path synthesis:** For simple results (≤2 tables, ≤50 rows), the synthesizer skips the LLM call and formats the data directly.

### 9.5 Validation (`validators.py`)

After execution, validates result quality:
- `adequate` → proceed to synthesis
- `inadequate` → replan (max 1 replan cycle)
- `needs_data` → escalate quick → simple

### 9.6 LLM Call Timeouts

| Node | Timeout |
|------|---------|
| Classify | 30 seconds |
| Plan | 90 seconds |
| Debug | 60 seconds |
| Synthesize | 60 seconds |
| Replan | 60 seconds |

---

## 10. Five Thinking Modes

### 10.1 Quick Mode (`subgraphs/quick.py`)

**Purpose:** Answer from schema context without executing any code.

**Flow:** `question → LLM answer from context → validate`

**Escalation:** If the LLM determines data is needed (`needs_data`), escalates to simple mode.

**Examples:** "What tables are in the database?", "Show me the ERD", "What columns does ins_cars have?"

### 10.2 Simple Mode (`subgraphs/simple.py`)

**Purpose:** Standard analytical queries with 1–5 execution steps.

**Flow:**
```
plan → execute step 1 → [debug if error]* → execute step 2 → ...
     → validate → [replan if inadequate] → synthesize
```

**Examples:** "Top 10 customers by revenue", "Average claim amount by brand"

### 10.3 Extended Mode (`subgraphs/extended.py`)

**Purpose:** Comprehensive analysis with 3–15 steps, iterative refinement.

**Flow:**
```
plan → execute steps → checkpoint (every 3 steps)
     → reflect on progress → [revise plan if needed]
     → continue execution → ... → validate → synthesize
```

**Special behavior:**
- Checkpoint interval: every 3 steps (configurable)
- `max_revisions=2` limit prevents infinite revision loops
- `skip_next_checkpoint` flag after revision to avoid immediate re-checkpoint
- Reflection step evaluates partial results and adjusts remaining plan

**Examples:** "Perform an EDA on the sales table", "Comprehensive churn analysis"

### 10.4 Optimization Mode (`subgraphs/optimization.py`)

**Purpose:** Large-table queries (>1M rows) with cost-aware execution.

**Flow:**
```
plan → cost_check (EXPLAIN) → strategy_gate (user prompt)
     → optimize_plan (apply sampling) → execute → synthesize
```

**Strategy options:**
- `SAMPLE` — execute on a representative sample (1–10%)
- `FULL` — execute full query (user accepts cost)
- `CANCEL` — abort the query

**Examples:** "Analyze all 50M transactions", "Distribution of order amounts"

### 10.5 Deep Mode (`subgraphs/deep.py`)

**Purpose:** Multi-investigation research with parallel reasoning.

**Flow:**
```
create_blueprint (2–5 investigations)
  → for each investigation:
       investigate (run as Simple mode sub-agent)
       → reason about findings
  → synthesize final report
```

**Blueprint schema:**
```json
{
    "overall_question": "...",
    "investigations": [
        {
            "id": 1,
            "question": "Sub-question to investigate",
            "approach": "How to investigate",
            "priority": "high|medium|low",
            "needs_visualization": true
        }
    ]
}
```

**Investigation normalization:** Blueprint limited to 2–5 investigations. Each investigation runs through the simple mode pipeline independently, with results streamed as they complete.

**Examples:** "Investigate customer churn patterns", "What insights can you find about damage costs?"

---

## 11. Async Reasoning Observer

**File:** `mcpdb/agent/observer.py`

### 11.1 Purpose

Non-blocking parallel monitor that tracks agent execution in real time, detects anomalies, and supports cooperative cancellation.

### 11.2 Components

**AsyncReasoningObserver:**
- Runs as an asyncio task alongside the agent
- Tracks phase timing (classify, plan, execute, debug, synthesize)
- Compares timing against per-mode expectations

**Timing expectations (warning, critical) in seconds:**

| Phase | Quick | Simple | Extended | Deep |
|-------|-------|--------|----------|------|
| Classify | 3, 10 | 3, 10 | 3, 10 | 3, 10 |
| Plan | 5, 15 | 10, 30 | 15, 45 | 20, 60 |
| Total | 15, 45 | 60, 180 | 300, 600 | 600, 1200 |

**Anomaly types:**
- `timing_warning` — phase exceeds warning threshold
- `timing_critical` — phase exceeds critical threshold
- `debug_loop` — excessive debug retries detected
- `empty_loop` — repeated empty results
- `stuck` — no progress for extended period

### 11.3 ObserverReport

```python
@dataclass
class ObserverReport:
    question: str
    mode: str
    total_time: float
    phase_times: dict[str, float]
    anomalies: list[Anomaly]
    step_count: int
    debug_count: int
    was_cancelled: bool
    observer_actions: list[str]
```

### 11.4 CancellationToken

**File:** `mcpdb/agent/cancellation.py`

Thread-safe cooperative cancellation:

```python
class CancellationToken:
    def cancel(self) -> None: ...       # Signal cancellation
    @property
    def is_cancelled(self) -> bool: ... # Check signal
    def check(self) -> None: ...        # Raise CancelledException if cancelled
    def reset(self) -> None: ...        # Clear signal for reuse
```

The token is wired through `AgentState` and checked at plan, execute, and synthesize boundaries.

---

## 12. Experience & Learning System

**Package:** `mcpdb/experience/`

### 12.1 Architecture

```
Question → Cache Lookup ──hit──→ Replay cached code → Return
                │
               miss
                │
          Run full agent
                │
          Stage result ──→ Background quality eval ──→ Promote / Reject
                                                          │
                                                     Anti-pattern
                                                     tracking
```

### 12.2 ExperienceService

**File:** `experience/service.py`

Central lifecycle manager owning: `ExperienceStore`, `ExperienceCache`, `StagingStore`, `QualityWorker`.

```python
class ExperienceService:
    async def start(self, llm: Any) -> None: ...  # Start background worker
    async def stop(self) -> None: ...              # Graceful shutdown (5s timeout)
    @property
    def is_running(self) -> bool: ...
    @property
    def worker_stats(self) -> dict[str, int]: ...  # promoted, rejected, errors
```

### 12.3 Two-Tier Cache

**File:** `experience/cache.py`

1. **Exact match** — `intent_hash` (MD5 of normalized question + source fingerprint)
2. **Semantic match** — `semantic_hash` (embedding similarity above threshold)

**Mode hierarchy:** `quick (0) < simple (1) < optimization (2) < extended (3) < deep (4)`

A cached result from a lower mode is not served for a higher-mode request. A `deep` cache hit satisfies a `simple` request.

**Cache validation:**
- Schema hash comparison (invalidate on schema drift)
- Max age check (configurable, default 30 days)
- In-memory LRU (max 200 entries)

### 12.4 Record Types

**File:** `experience/records.py`

```python
@dataclass
class CodeStep:
    action_type: str    # sql | python | schema | sample
    code: str
    result_preview: str
    time_ms: int

@dataclass
class SuccessRecord:
    intent_hash: str
    question: str
    source_fingerprint: str
    schema_hash: str
    query_mode: str
    steps: list[CodeStep]
    response: str
    timestamp: float
    metadata: dict
    semantic_hash: str
    plan_metadata: dict  # analysis, approach, step_descriptions, blueprint

@dataclass
class StagedRecord:
    # Same fields as SuccessRecord, plus:
    staged_at: float
    evaluated: bool
    # Converts to SuccessRecord on promotion:
    def to_success_record(self) -> SuccessRecord: ...

@dataclass
class QualityResult:
    score: int           # 1-10
    completeness: int    # 1-10
    accuracy: int
    relevance: int
    clarity: int
    issues: list[str]
    verdict: str         # "promote" | "reject"

@dataclass
class FailureRecord:
    question: str
    source_fingerprint: str
    error_type: str
    error_message: str
    failed_code: str
    timestamp: float
```

### 12.5 Staging & Quality Evaluation

**StagingStore** (`experience/staging.py`):
- JSONL files per source fingerprint at `~/.mcpdb/experience/staging/`
- Thread-safe via `threading.Lock()`

**QualityEvaluator** (`experience/evaluator.py`):
- LLM-based scoring on 4 dimensions: completeness, accuracy, relevance, clarity
- Quick-mode responses with no executable steps: auto-promoted (score 10)
- Red flags: hallucinated numbers, missing findings, contradictions, generic answers
- Minimum score for promotion: 7 (configurable)

**QualityWorker** (`experience/worker.py`):
- Background asyncio task polling staging store
- Evaluates pending records, promotes or rejects based on QualityResult
- Configurable poll interval (default 30s), max retries (default 3)

### 12.6 Anti-Pattern Tracking

**File:** `experience/antipatterns.py`

```python
class AntiPatternTracker:
    def record_failure(self, question, source_metadata,
                       error_type, error_message, failed_code=""): ...
    def get_anti_pattern_context(self, source_metadata) -> str: ...
```

- Groups repeated failures by error type and source
- Triggers when `min_occurrences` reached (default: 2)
- Injects context into planning prompts: "Avoid these known failure patterns: ..."

---

## 13. LLM Integration Layer

**Package:** `mcpdb/llm/`

### 13.1 Provider Interface

**File:** `llm/provider.py`

```python
class LLMProvider(ABC):
    @abstractmethod
    async def stream(self, messages: list[Message],
                     system: str | None = None) -> AsyncIterator[StreamChunk]: ...
    async def generate(self, messages: list[Message],
                       system: str | None = None) -> str: ...  # Convenience wrapper

@dataclass
class Message:
    role: str       # "user" | "assistant" | "system"
    content: str

@dataclass
class StreamChunk:
    text: str
    usage: TokenUsage | None  # Only on final chunk
```

### 13.2 Provider Factory

**File:** `llm/factory.py`

```python
def create_provider(provider_name: str, model: str = "",
                    api_key: str = "", **kwargs) -> LLMProvider:
```

| Provider | Default Model | SDK | API Key Env Var |
|----------|--------------|-----|-----------------|
| `gemini` | `gemini-2.5-pro` | google-genai | `GEMINI_API_KEY` |
| `openai` | `gpt-4.1` | openai | `OPENAI_API_KEY` |
| `anthropic` | `claude-sonnet-4-6` | anthropic | `ANTHROPIC_API_KEY` |
| `ollama` | `llama3.1` | httpx | (none, local) |

**Auto-resolution:** If `api_key` is empty, the factory checks the corresponding environment variable.

**FallbackProvider:** Tries multiple providers in sequence; yields on first success.

### 13.3 JSON Extraction & Repair

**File:** `llm/provider.py`

LLM responses often contain JSON embedded in markdown or with syntax errors. Two utilities handle this:

**`_extract_json(text: str) -> dict | list`**
- Strips markdown code fences
- Finds first `{` or `[` and matches to closing bracket
- Falls back to regex patterns

**`_repair_json(text: str) -> str`**
- Removes trailing commas before `}` or `]`
- Closes unclosed string literals
- Closes unclosed braces/brackets (stack-based matching)

These are called on every LLM response that expects structured JSON (classification, planning, debugging).

### 13.4 Default Configuration

- No hardcoded `max_tokens` — provider default (16384) used everywhere
- Temperature: 0.0 (deterministic)
- Budget per question: $2.00 (configurable)

---

## 14. Python Execution Sandbox

**Package:** `mcpdb/sandbox/`

### 14.1 Execution Model

**File:** `sandbox/executor.py`

Python code runs in an **isolated subprocess** (not in-process):

1. Wrapper script injected with pre-imported libraries and security checks
2. Context DataFrame (`df`) injected from the preceding SQL step
3. `plt.show()` and `plt.savefig()` monkey-patched to capture figures as base64 PNG
4. Resource limits applied via `resource.setrlimit()` on Linux

**SandboxResult:**
```python
@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    success: bool
    error: str | None
    dataframe: pd.DataFrame | None
    charts: list[str]        # base64 PNG images
    return_value: Any
```

### 14.2 Security Configuration

**File:** `sandbox/security.py`

**Default allowed modules:**
- **Data:** pandas, numpy, polars, pyarrow, duckdb, sqlalchemy
- **ML/Science:** sklearn, torch, xgboost, lightgbm, catboost, scipy
- **Visualization:** matplotlib, seaborn, plotly
- **NLP:** nltk, spacy, transformers
- **Geo/Image:** geopandas, shapely, PIL
- **Stdlib:** json, re, math, datetime, collections, itertools, statistics, csv, io, random, hashlib, etc.

**Default blocked modules:**
`os`, `sys`, `subprocess`, `shutil`, `pathlib`, `socket`, `http`, `urllib`, `requests`, `pickle`, `ctypes`, `threading`, `multiprocessing`, `importlib`

**Import validation:** `SandboxSecurity.validate_imports(code)` scans AST for import statements and returns violations.

**Resource limits:**
- Memory: 2048 MB (configurable)
- CPU time: 60 seconds (configurable)
- Applied via `resource.RLIMIT_AS` and `resource.RLIMIT_CPU` on Linux

**Security modes:**
- Normal: allow list + block list enforced
- `allow_all=True`: only block list enforced
- `allow_all=True` + empty block list: security disabled

---

## 15. Security

**Package:** `mcpdb/security/`

### 15.1 SQL Safety (`sql_safety.py`)

**Read-only enforcement** (default on):
- Blocks: INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, GRANT, REVOKE, EXEC
- Raises `SQLSafetyError` with specific violation details

**Injection detection:**
- Multi-statement (`;DROP`)
- SQL comments (`--`)
- UNION + information_schema
- INTO OUTFILE / DUMPFILE
- LOAD DATA

**Identifier sanitization:** `sanitize_identifier()` strips non-alphanumeric characters, quotes reserved words.

### 15.2 Credential Redaction (`credentials.py`)

- `redact_connection_string()` — replaces password with `***`
- `redact_log_message()` — regex-based redaction in log output
- `redact_dict()` — scrubs sensitive keys from dictionaries

### 15.3 Rate Limiting (`rate_limiter.py`)

- Per-session query rate limits
- Concurrency limits
- Circuit breaker with automatic backoff on repeated failures
- Custom exceptions: `RateLimitExceeded`, `CircuitBreakerOpen`

---

## 16. MCP Server — Tools, Resources & Prompts

**Package:** `mcpdb/mcp/`

### 16.1 Server Setup (`server.py`)

```python
def create_server(config: McpdbConfig | None = None,
                  experience_service: ExperienceService | None = None
                  ) -> tuple[Server, SourceRegistry]:
```

Creates an MCP server with:
1. LLM provider from config
2. All tools registered via dispatcher
3. Resources (schema, ERD)
4. Prompts (explore_source, deep_table_analysis)

**Transport:** stdio (MCP clients) or SSE (web/remote clients).

### 16.2 Tool Dispatcher (`tools/__init__.py`)

**Single dispatcher pattern:** one `list_tools()` / `call_tool()` pair routes to all 33 tools.

Tool modules collected from: session, querying, discovery, profiling, relationships, excel, analysis, export, experience, control.

Each module exports a `get_tools()` function returning tool definitions with schemas and handlers.

**Handler wrapping:** auto-awaits coroutines from async handlers. Error handling catches `SourceNotFoundError` and returns a helpful message.

### 16.3 Tool Categories (33 Tools)

**Session (6):**
`connect_database`, `load_csv_files`, `list_sources`, `remove_source`, `get_source_schema`, `get_session_status`

**Querying (4):**
`execute_sql`, `get_table_sample`, `validate_sql`, `cross_source_query`

**Discovery (3):**
`search_schema`, `explain_query`, `render_erd`

**Profiling (2):**
`profile_table`, `profile_column`

**Relationships (2):**
`find_relationships`, `suggest_joins`

**Excel (5):**
`load_excel`, `list_sheets`, `read_range`, `extract_excel_table`, `explain_formula`

**Analysis (2):**
`ask_question`, `suggest_followups`

**Export (1):**
`export_conversation`

**Experience (5):**
`get_experience_stats`, `list_cached_queries`, `invalidate_cache_entry`, `clear_experience`, `vote_response`

**Control (3):**
`cancel_execution`, `add_context`, `submit_strategy`

### 16.4 MCP Resources (`resources.py`)

URI-based resource templates:

| URI Pattern | MIME Type | Content |
|-------------|-----------|---------|
| `schema://{source_id}` | application/json | Full schema as JSON |
| `erd://{source_id}` | text/plain | Mermaid ER diagram |

### 16.5 MCP Prompts (`prompts.py`)

| Prompt | Arguments | Purpose |
|--------|-----------|---------|
| `explore_source` | source_id | Guided multi-step exploration workflow |
| `deep_table_analysis` | source_id, table_name | In-depth analysis of a specific table |

---

## 17. Web Client

**Package:** `mcpdb/web/`

### 17.1 Architecture

FastAPI application with WebSocket event streaming. No npm, no React, no build step — a single `index.html` template with inline CSS and JS, CDN-loaded libraries (marked.js, highlight.js, mermaid.js).

### 17.2 REST Endpoints (`app.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serve HTML template |
| GET | `/api/health` | Version, source count, LLM info |
| GET | `/api/sources` | List connected sources with metadata |
| POST | `/api/connect` | Connect database by connection string |
| POST | `/api/upload/csv` | Upload CSV file (500MB limit) |
| POST | `/api/upload/excel` | Upload Excel file (500MB limit) |
| DELETE | `/api/sources/{id}` | Remove a source |
| POST | `/api/export/{format}` | Export conversation (html/pdf/notebook) |
| GET | `/api/export/view/{token}` | Retrieve exported file (one-time use) |
| GET | `/api/llm/config` | Get current LLM configuration |
| PUT | `/api/llm/config` | Update LLM provider/model |
| WS | `/ws` | WebSocket for query execution |

### 17.3 WebSocket Protocol

Client sends a query message, server streams events:

```json
// Client → Server
{"type": "query", "question": "...", "mode": "auto"}
{"type": "cancel"}
{"type": "rethink"}

// Server → Client (20+ event types)
{"type": "classify/start"}
{"type": "classify/complete", "mode": "simple", "reasoning": "..."}
{"type": "plan/start"}
{"type": "plan/ready", "steps": [...]}
{"type": "execute/step/start", "step": 1, "action": "sql", "code": "..."}
{"type": "execute/step/complete", "step": 1, "rows": 42, "time_ms": 123}
{"type": "execute/step/error", "step": 1, "error": "...", "attempt": 1}
{"type": "debug/start", "step": 1, "attempt": 2}
{"type": "debug/complete", "step": 1, "fixed_code": "..."}
{"type": "chart", "image": "data:image/png;base64,..."}
{"type": "synthesize/start"}
{"type": "synthesize/complete", "response": "..."}
{"type": "agent/complete", "cached": false, "time_ms": 4200}
{"type": "experience/cache_hit", "question": "...", "response": "..."}
{"type": "experience/rethink"}
{"type": "followups", "suggestions": ["...", "...", "..."]}
{"type": "observer/report", "report": {...}}
{"type": "error", "message": "..."}
```

### 17.4 Per-WebSocket Task Tracking

Each WebSocket connection gets a unique `ws_id` from an atomic counter. Active tasks are tracked per-connection in `_active_tasks[ws_id]`, preventing race conditions between concurrent connections.

### 17.5 Web UI Features

- **3-panel layout:** Sources & schema (left), chat (center), execution monitor (right)
- **Source management:** Connect databases, upload CSV/Excel from browser
- **Execution monitor:** Phase pipeline (Classify → Plan → Execute → Validate → Synthesize), timing, activity log
- **Chart rendering:** Matplotlib/seaborn charts displayed inline as base64 images
- **Mermaid diagrams:** ER diagrams rendered via mermaid.js
- **Markdown rendering:** Syntax-highlighted code, GFM tables, formatted text
- **Follow-up suggestions:** 3–5 context-aware suggestions after every response
- **Mode selector:** Auto/Quick/Simple/Extended/Optimization/Deep dropdown
- **Deep mode streaming:** Investigation results appear as they complete
- **Export buttons:** HTML report, PDF, Jupyter notebook

---

## 18. CLI, REPL & TUI

**Package:** `mcpdb/cli/`

### 18.1 One-Shot Query (`__main__.py`)

```bash
mcpdb query <source> <question> [--no-cache]
```

Runs a single question against a data source and exits. Uses `RichProgress` for pipeline display.

### 18.2 Rich Progress Display (`cli/progress.py`)

Replaces the braille spinner with a full Rich-based pipeline view:

```
✓ Classify   0.8s   simple (3 entities)
✓ Plan       2.1s   2 steps
● Execute    1/2    ━━━━━━━━━━━━━━━━━━━━ 50%
◌ Synthesize
```

**Phase states:** PENDING (◌), RUNNING (●), COMPLETE (✓), ERROR (✗), SKIPPED (○)

**Mode colors:** quick=green, simple=blue, extended=yellow, optimization=magenta, deep=red

### 18.3 Interactive REPL (`cli/repl.py`)

```bash
mcpdb repl <source> [--no-cache]
```

**Features:**
- Persistent session with conversation history
- prompt_toolkit for input (fallback to built-in `input()`)
- Commands: `/help`, `/mode <mode|auto>`, `/source list`, `/schema [table]`, `/history`, `/export <markdown|json>`, `/cache`, `/quit`
- Follow-up suggestions: type a number (1, 2, 3) to pick
- Ctrl+C cancels running query via CancellationToken

### 18.4 Textual TUI (`cli/tui/app.py`)

```bash
mcpdb tui <source> [--no-cache]
```

Windowed terminal UI built with Textual:
- Source panel with connected sources and metadata
- Pipeline bar with animated phase indicators
- Query input with history
- Scrollable result view
- Real-time event log

---

## 19. Export System

**Package:** `mcpdb/web/export.py`

### 19.1 HTML Export

Self-contained single-file HTML report:
- Markdown → HTML (via `markdown` library)
- Mermaid diagrams rendered to SVG via kroki.io or mermaid.ink
- Charts embedded as base64 `<img>` tags
- Inline CSS for styling (print-friendly)
- Tables with proper formatting

### 19.2 PDF Export

HTML → PDF via WeasyPrint:
- Same rendering pipeline as HTML export
- `weasyprint>=62` required
- Supports page breaks, headers, footers

### 19.3 Jupyter Notebook Export

Generates `.ipynb` with re-runnable code:

1. **Setup cell** — pip installs, imports (pandas, numpy, matplotlib, seaborn, sqlalchemy), `db_query()` helper function, database connection
2. **Per-turn cells:**
   - Markdown header: "Turn N: {question}" with mode badge
   - Code cells for each SQL step (`df = db_query("SELECT ...")`)
   - Code cells for each Python step (matplotlib charts, etc.)
   - Markdown cells for synthesized text
3. **ERD cell** — Mermaid diagram rendered via mermaid.ink as `<img>` in an HTML iframe
4. **Security notice** — warns about embedded connection credentials

**CSV/Excel notebooks:** Use pandas `read_csv()`/`read_excel()` instead of `db_query()`.

---

## 20. Configuration

**File:** `mcpdb/config.py`

### 20.1 Config Loading

Search order:
1. Explicit path argument
2. `MCPDB_CONFIG` environment variable
3. `./mcpdb.yaml` in current directory
4. Built-in defaults (no file needed)

Environment variables resolved with `${VAR_NAME}` syntax.

### 20.2 Configuration Schema

```python
@dataclass
class McpdbConfig:
    llm: LLMConfig
    server: ServerConfig
    execution: ExecutionConfig
    cost_gate: CostGateConfig
    duckdb: DuckDBConfig
    experience: ExperienceConfig
    ui: UIConfig
    sandbox: SandboxConfig

@dataclass
class LLMConfig:
    reasoning: LLMModelConfig  # provider, model, api_key
    fast: LLMModelConfig       # lighter model for simple ops
    temperature: float = 0.0
    timeout: int = 120
    budget_per_question_usd: float = 2.00

@dataclass
class ServerConfig:
    transport: str = "stdio"   # stdio | sse
    host: str = "localhost"
    port: int = 8765

@dataclass
class ExecutionConfig:
    query_timeout: int = 30
    python_timeout: int = 60
    max_rows_display: int = 100
    read_only: bool = True

@dataclass
class CostGateConfig:
    enabled: bool = True
    auto_mode: bool = False
    large_table_threshold: int = 1_000_000

@dataclass
class DuckDBConfig:
    memory_limit: str = "2GB"
    threads: int = 4

@dataclass
class ExperienceConfig:
    enabled: bool = True
    storage_dir: str = "~/.mcpdb/experience"
    embedding_provider: str = "auto"
    max_success_records: int = 2000
    max_failure_records: int = 500
    cache_max_age_days: int = 30
    quality_eval_enabled: bool = True
    quality_eval_min_score: int = 7
    quality_eval_poll_interval: float = 30.0
    quality_eval_max_retries: int = 3

@dataclass
class SandboxConfig:
    allowed_modules: list[str] = field(default_factory=list)
    blocked_modules: list[str] = field(default_factory=list)
    allow_all: bool = False
    memory_mb: int = 2048
    cpu_seconds: int = 60
```

---

## 21. Data Models & Type Contracts

### 21.1 Plan Schema

```json
{
    "analysis": "What the user wants",
    "approach": "How we'll get it",
    "steps": [
        {
            "step_number": 1,
            "action": "sql|python|schema|sample",
            "source_id": "source_id",
            "description": "What this step does",
            "code": "SELECT ... or import matplotlib...",
            "status": "pending|success|error",
            "attempts": 0
        }
    ]
}
```

### 21.2 Artifact Types

Artifacts are produced during execution and stored in `AgentState["artifacts"]`:

**Table artifact:**
```json
{
    "type": "table",
    "columns": ["name", "value"],
    "rows": [["Alice", 42], ["Bob", 37]],
    "truncated": false,
    "total_rows": 2
}
```

**Chart artifact:**
```json
{
    "type": "chart",
    "image_base64": "iVBOR...",
    "format": "png"
}
```

**Cell grid artifact (Excel):**
```json
{
    "type": "cell_grid",
    "sheet": "Sheet1",
    "range": "A1:D6",
    "cells": [[{"value": "Dept", "formula": null}, ...]],
    "merged_regions": [{"min_row": 1, "min_col": 1, "max_row": 1, "max_col": 3}]
}
```

### 21.3 Execution Log Entry

Each step produces a log entry in `AgentState["execution_log"]`:

```json
{
    "step_number": 1,
    "action": "sql",
    "source_id": "db_abc123",
    "code": "SELECT ...",
    "status": "success|error|timeout",
    "result_preview": "First 200 chars...",
    "time_ms": 234,
    "artifacts_produced": ["chart_1"],
    "error": null
}
```

---

## 22. Error Handling

### 22.1 Error Categories

| Category | Examples | Recovery |
|----------|----------|----------|
| Connection | DB unreachable, timeout, auth failure | Retry with backoff (3 attempts) |
| Query syntax | Invalid SQL, wrong column names | LLM debug → fix → retry (3 attempts) |
| Query timeout | Statement timeout on large scan | Suggest optimization strategy |
| Python error | Runtime error in sandbox | LLM debug → fix → retry (3 attempts) |
| File error | CSV encoding issue, corrupt Excel | Report clearly, suggest alternatives |
| LLM error | API timeout, rate limit | Retry with backoff, fallback to fast model |
| Resource error | Out of memory, disk full | Report, suggest reducing scope |

### 22.2 Debug Loop

```
execute_step → ERROR
    ↓
Capture: error type, message, traceback, code
    ↓
Check experience for similar error fixes
    ↓
LLM debug prompt: schema + code + error + similar fixes
    ↓
LLM returns: {error_analysis, fix_description, corrected_code}
    ↓
Retry step with corrected code
    ↓
Max 3 retries → advance past step on final failure
```

The debug node advances past a permanently failing step to prevent infinite loops. Partial results from successful steps are preserved.

### 22.3 Graceful Degradation

- Primary LLM unavailable → fall back to fast model
- DuckDB out of memory → suggest loading fewer files
- Excel file corrupted → report which sheets are readable
- Source disconnects mid-analysis → report partial results
- Plan retry: LLM → simpler LLM → hardcoded fallback plan

---

## 23. Testing

### 23.1 Test Suite

**1089 tests** across 58 test files. All unit tests use SQLite (no external DB needed).

| Category | Tests | Coverage |
|----------|-------|----------|
| Agent modes | ~200 | All 5 modes, escalation, cancellation |
| Sources | ~150 | Database (5 dialects), CSV, Excel |
| LLM providers | ~50 | All 4 providers, fallback, JSON repair |
| MCP tools | ~100 | All 33 tools, error handling |
| Experience | ~100 | Cache, staging, evaluation, anti-patterns |
| Security | ~50 | SQL safety, sandbox, credential redaction |
| Web client | ~80 | REST endpoints, WebSocket, export |
| CLI | ~80 | Rich progress, REPL, TUI |
| Export | ~60 | HTML, PDF, notebook generation |
| Bootstrap | ~50 | Version, discovery, config loading |

### 23.2 Eval Suite

100-question evaluation against the `bgins` database (Bulgarian insurance, 21 tables, MySQL):

- **94 PASS, 1 PARTIAL, 5 FAIL** (94.0% pass rate)
- Scoring: 10% numeric tolerance, ground-truth value checking
- Failures: Q6/Q7 (data drift), Q62 (age calc), Q83 (agent bug), Q87 (ratio ambiguity)
- Mode timing: quick ~12s, simple ~25s, extended ~164s, deep ~788s

### 23.3 Productization Battery

175 queries across DB/CSV/Excel sources: **93.1% pass rate**

12/12 web e2e tests (Playwright) passing.

---

## 24. Project Structure

```
mcpdb/
├── __init__.py              # Version: 5.3.0
├── __main__.py              # CLI entry point, USAGE, MANUAL
├── config.py                # YAML config with env var resolution
├── logging.py               # Logging setup
│
├── agent/                   # LangGraph agent orchestration
│   ├── graph.py             # run_agent() — main entry, cache, observer
│   ├── state.py             # AgentState TypedDict
│   ├── callbacks.py         # CallbackManager for event dispatch
│   ├── cancellation.py      # CancellationToken (thread-safe)
│   ├── observer.py          # AsyncReasoningObserver
│   ├── user_input.py        # User input handling for cost gate
│   ├── nodes/
│   │   ├── classify.py      # Question → mode classification
│   │   ├── common.py        # make_plan, execute_steps, synthesize
│   │   ├── validators.py    # validate_result, replan
│   │   ├── extended.py      # Checkpoint/revision nodes
│   │   ├── cost_check.py    # EXPLAIN-based cost estimation
│   │   └── strategy_gate.py # SAMPLE/FULL/CANCEL user prompt
│   └── subgraphs/
│       ├── quick.py         # Context-only answers
│       ├── simple.py        # Plan → execute → synthesize
│       ├── extended.py      # With checkpoints + reflection
│       ├── optimization.py  # Cost-gated execution
│       └── deep.py          # Multi-investigation research
│
├── sources/                 # Data source abstraction
│   ├── base.py              # DataSource, QueryableSource, SpreadsheetSource ABCs
│   ├── registry.py          # SourceRegistry (thread-safe)
│   ├── federation.py        # Cross-source query via DuckDB
│   ├── database/
│   │   ├── source.py        # DatabaseSource
│   │   ├── connector.py     # SQLAlchemy engine + retry
│   │   ├── schema_explorer.py # Table/column introspection
│   │   └── dialects/        # PostgreSQL, MySQL, SQLite, MSSQL, Oracle
│   ├── csv/
│   │   ├── source.py        # CsvSource
│   │   ├── loader.py        # Encoding/delimiter/header detection
│   │   └── duckdb_backend.py
│   └── excel/
│       ├── source.py        # ExcelSource (dual mode)
│       ├── workbook_reader.py
│       ├── structure_analyzer.py
│       ├── cell_grid.py
│       ├── formula_deps.py
│       ├── formula_clusters.py
│       └── multi_workbook.py
│
├── llm/                     # LLM provider abstraction
│   ├── provider.py          # LLMProvider ABC, _extract_json, _repair_json
│   ├── factory.py           # create_provider(), FallbackProvider
│   ├── gemini_provider.py
│   ├── openai_provider.py
│   └── ollama_provider.py
│
├── sandbox/                 # Secure Python execution
│   ├── executor.py          # Subprocess wrapper, chart capture
│   └── security.py          # Allow/block lists, resource limits
│
├── security/                # Security hardening
│   ├── sql_safety.py        # Read-only enforcement, injection detection
│   ├── credentials.py       # Connection string redaction
│   └── rate_limiter.py      # Rate limits, circuit breaker
│
├── experience/              # Learning system
│   ├── service.py           # ExperienceService (lifecycle)
│   ├── cache.py             # Two-tier cache (exact + semantic)
│   ├── records.py           # SuccessRecord, StagedRecord, FailureRecord, QualityResult
│   ├── staging.py           # StagingStore (JSONL per source)
│   ├── evaluator.py         # QualityEvaluator (LLM-based scoring)
│   ├── worker.py            # QualityWorker (background async eval)
│   ├── antipatterns.py      # AntiPatternTracker
│   ├── store.py             # ExperienceStore (JSONL persistence)
│   ├── fingerprint.py       # Source identity hashing
│   ├── retriever.py         # Semantic similarity search
│   ├── embeddings.py        # Embedding providers
│   └── strategy_records.py  # Cost gate strategy tracking
│
├── mcp/                     # MCP protocol layer
│   ├── server.py            # create_server(), run_stdio_server()
│   ├── resources.py         # schema://, erd:// resource templates
│   ├── prompts.py           # explore_source, deep_table_analysis
│   ├── tool_visibility.py   # Dynamic tool visibility
│   └── tools/               # 33 tools across 10 categories
│       ├── __init__.py      # Central dispatcher
│       ├── session.py
│       ├── querying.py
│       ├── discovery.py
│       ├── profiling.py
│       ├── relationships.py
│       ├── excel.py
│       ├── analysis.py
│       ├── export.py
│       ├── experience.py
│       └── control.py
│
├── web/                     # Web client
│   ├── app.py               # FastAPI + WebSocket + REST
│   ├── export.py            # HTML/PDF/notebook generation
│   └── templates/
│       └── index.html       # Single-page UI (CSS + JS inline)
│
├── cli/                     # Terminal interfaces
│   ├── __init__.py
│   ├── progress.py          # Rich pipeline display
│   ├── renderer.py          # Result rendering (tables, code, errors)
│   ├── repl.py              # Interactive REPL
│   └── tui/
│       ├── __init__.py
│       └── app.py           # Textual TUI application
│
├── session/                 # Session management
│   ├── __init__.py
│   └── session_manager.py   # Persistent sessions
│
└── export/                  # (Legacy, now in web/export.py)
```
