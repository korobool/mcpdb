# MCPDB: Multi-Source Data Intelligence Agent

## Technical Specification v1.0

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Overview & Goals](#2-system-overview--goals)
3. [Architecture Overview](#3-architecture-overview)
4. [Data Source Abstraction Layer](#4-data-source-abstraction-layer)
5. [Database Source Module](#5-database-source-module)
6. [CSV Source Module](#6-csv-source-module)
7. [Excel Source Module](#7-excel-source-module)
8. [Multi-File Session Manager](#8-multi-file-session-manager)
9. [LangGraph Agent Orchestration — Five Thinking Modes](#9-langgraph-agent-orchestration)
10. [Streaming Event Protocol, Cancellation & User Interaction](#10-streaming-event-protocol-cancellation--user-interaction)
11. [Per-Source Experience & Learning System](#11-per-source-experience--learning-system)
12. [MCP Server — Tools, Resources & Prompts](#12-mcp-server--tools-resources--prompts)
13. [LLM Integration Layer](#13-llm-integration-layer)
14. [Python Execution Sandbox](#14-python-execution-sandbox)
15. [Frontend (Python UI)](#15-frontend-python-ui)
16. [Configuration & Environment](#16-configuration--environment)
17. [Project Structure](#17-project-structure)
18. [Data Models & Type Contracts](#18-data-models--type-contracts)
19. [Error Handling Strategy](#19-error-handling-strategy)
20. [Testing Strategy](#20-testing-strategy)
21. [Deployment & Packaging](#21-deployment--packaging)
22. [Implementation Phases](#22-implementation-phases)
23. [Appendix A: Prompt Templates](#appendix-a-prompt-templates)
24. [Appendix B: MCP Tool Schemas](#appendix-b-mcp-tool-schemas)
25. [Appendix C: Reference Architecture from dbtalk](#appendix-c-reference-architecture-from-dbtalk)

---

## 1. Executive Summary

**MCPDB** is a production-grade agentic system that enables natural language interaction with **databases**, **CSV files**, and **Excel workbooks**. It is architected as a **LangGraph-based agent** exposed through the **Model Context Protocol (MCP)**, making it usable from any MCP-compatible client (Claude Desktop, IDE extensions, custom frontends, CLI tools).

The system reimplements and extends the functionality of the existing `dbtalk` Streamlit monolith — a proven talk-to-data agent with 4-mode query classification, self-healing execution, cost gating, per-source experience learning, and rich visualization — into a **decoupled, extensible, multi-source architecture**.

### Key Differentiators from dbtalk

| Aspect | dbtalk (current) | MCPDB (new) |
|--------|-----------------|-------------|
| Architecture | Streamlit monolith | Decoupled MCP server + LangGraph agent + UI |
| Data sources | 5 SQL databases | 5 SQL databases + CSV + Excel |
| Excel handling | N/A | Full: formulas, merged cells, multi-sheet, non-rectangular |
| CSV handling | N/A | Multi-file, auto-detection, cross-file joins |
| Client support | Streamlit only | Any MCP client (Claude Desktop, IDEs, CLI, custom UI) |
| LLM provider | Google Gemini only | Provider-agnostic (Anthropic Claude default, pluggable) |
| UI | Streamlit | Custom Python UI (NiceGUI/Panel) |
| Tool exposure | Internal only | MCP tools (standardized, discoverable) |
| Multi-file | N/A | Unified session across DBs + files |

---

## 2. System Overview & Goals

### 2.1 Functional Goals

1. **Natural language querying** of databases (PostgreSQL, MySQL, SQLite, SQL Server, Oracle)
2. **Natural language analysis** of CSV files (single and multi-file, with cross-file operations)
3. **Natural language exploration** of Excel workbooks (formulas, non-rectangular data, multi-sheet)
4. **Mixed-source analysis** — join/combine data across databases, CSVs, and Excel files in a single conversation
5. **Intelligent query routing** — classify questions into execution modes (quick/simple/extended/optimization)
6. **Self-healing execution** — auto-detect and fix errors with LLM-assisted debugging
7. **Rich output** — tables, charts (matplotlib/seaborn), markdown, LaTeX, Mermaid diagrams
8. **Cost-aware execution** — estimate query cost, gate expensive operations
9. **Per-source learning** — experience system with exact-match code caching, template reuse, anti-pattern avoidance, and cross-dialect knowledge transfer
10. **Export** — PDF, HTML, Jupyter notebook export of conversations

### 2.2 Non-Functional Goals

1. **MCP-first** — all capabilities exposed as MCP tools; UI is just one client
2. **Provider-agnostic** — LLM abstraction supporting Claude (default), GPT-4, Gemini, local models
3. **Extensible** — adding a new data source type requires implementing one interface
4. **Testable** — each layer independently testable; subgraphs testable in isolation
5. **Secure** — read-only mode by default, sandboxed Python execution, no credential leakage
6. **Observable** — structured logging, execution metrics, streaming events

### 2.3 Explicit Non-Goals

- Real-time streaming data (Kafka, etc.)
- Data modification (INSERT/UPDATE/DELETE) — read-only by default
- Database administration (schema changes, user management)
- ETL pipelines or scheduled jobs

---

## 3. Architecture Overview

### 3.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP CLIENTS                              │
│  ┌──────────┐  ┌──────────────┐  ┌─────┐  ┌────────────────┐   │
│  │Claude    │  │IDE Extensions│  │ CLI │  │ MCPDB Frontend │   │
│  │Desktop   │  │(VS Code etc.)│  │     │  │ (Python UI)    │   │
│  └────┬─────┘  └──────┬───────┘  └──┬──┘  └───────┬────────┘   │
│       │               │             │              │            │
└───────┼───────────────┼─────────────┼──────────────┼────────────┘
        │               │             │              │
        └───────────────┴──────┬──────┴──────────────┘
                               │
                    ┌──────────▼──────────┐
                    │    MCP SERVER       │
                    │  (Transport Layer)  │
                    │  stdio / SSE / WS   │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │   TOOL REGISTRY     │
                    │  (MCP Tool Defs)    │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼──────┐ ┌──────▼───────┐ ┌──────▼───────┐
    │  SESSION TOOLS  │ │ SOURCE TOOLS │ │ ANALYSIS     │
    │  - connect_db   │ │ - query_sql  │ │  TOOLS       │
    │  - load_csv     │ │ - query_csv  │ │ - ask        │
    │  - load_excel   │ │ - read_excel │ │ - visualize  │
    │  - list_sources │ │ - run_python │ │ - export     │
    └─────────┬──────┘ └──────┬───────┘ └──────┬───────┘
              │               │                │
              └───────────────┼────────────────┘
                              │
                   ┌──────────▼──────────┐
                   │   LANGGRAPH AGENT   │
                   │   (Orchestrator)    │
                   │                     │
                   │  classify → route   │
                   │  ┌───────────────┐  │
                   │  │ Quick  SG     │  │
                   │  │ Simple SG     │  │
                   │  │ Extended SG   │  │
                   │  │ Optimization  │  │
                   │  └───────────────┘  │
                   └──────────┬──────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼─────┐ ┌──────▼──────┐ ┌──────▼──────┐
    │  DB SOURCES   │ │ CSV SOURCES │ │EXCEL SOURCES│
    │  (Dialects)   │ │ (DuckDB)   │ │ (openpyxl)  │
    │               │ │             │ │             │
    │ PostgreSQL    │ │ Auto-detect │ │ Formulas    │
    │ MySQL         │ │ Multi-file  │ │ Merged cells│
    │ SQLite        │ │ Cross-join  │ │ Multi-sheet │
    │ SQL Server    │ │             │ │ Non-rect    │
    │ Oracle        │ │             │ │             │
    └───────────────┘ └─────────────┘ └─────────────┘
```

### 3.2 Dual-Mode Architecture: Tool Mode vs Agent Mode

The MCP server supports **two complementary usage patterns**. This is a critical architectural choice — the system is NOT a monolith behind a single `ask_question` endpoint.

```
MODE A: TOOL MODE (client orchestrates)
┌────────────────────────────────────────────────────────────────┐
│  CLIENT LLM (Claude Desktop, IDE, custom)                      │
│                                                                 │
│  "User asks: top customers by revenue"                         │
│  Client LLM decides:                                           │
│    1. Call search_schema("customer", "revenue")                │
│    2. Call generate_sql("top customers by revenue")            │
│    3. Call execute_sql(generated_sql)                           │
│    4. Call suggest_visualization(result)                        │
│    5. Call execute_python(chart_code)                           │
│  Client LLM synthesizes answer from tool results               │
└────────────────────────────────────────────────────────────────┘

MODE B: AGENT MODE (server orchestrates)
┌────────────────────────────────────────────────────────────────┐
│  CLIENT                                                         │
│    1. Call ask_question("top customers by revenue")             │
│    2. Observe streaming events (plan, execute, debug, ...)     │
│    3. Optionally: add_context(), cancel_execution()            │
│    4. Receive complete answer with artifacts                    │
│                                                                 │
│  SERVER (LangGraph agent handles everything internally)         │
└────────────────────────────────────────────────────────────────┘

MODE C: HYBRID (client starts agent, intervenes as needed)
┌────────────────────────────────────────────────────────────────┐
│  CLIENT                                                         │
│    1. Call ask_question("analyze sales trends")                 │
│    2. Observe streaming: agent plans 5 steps                   │
│    3. After step 3, call add_context("also compare by region") │
│    4. Or: cancel_execution(), then manually call tools          │
└────────────────────────────────────────────────────────────────┘
```

**Why both modes matter**:
- **Tool Mode** lets sophisticated clients (Claude Desktop, Cursor) leverage their own reasoning while using MCPDB for data access. The client picks which tools to call and in what order.
- **Agent Mode** provides the full 5-mode intelligence pipeline for clients that want turnkey analysis. This is where the specialized LangGraph agent with self-healing, cost gating, and experience learning shines.
- **Hybrid Mode** combines both — the agent runs autonomously but the client can steer, inject context, or take over mid-execution.

Every capability available in Agent Mode MUST also be available as a standalone tool in Tool Mode. The agent is composed FROM the same tools the client can call directly.

### 3.3 Core Design Principles

1. **Source-agnostic agent logic** — the LangGraph orchestrator doesn't know or care whether data comes from a database, CSV, or Excel. It works with a unified `DataSource` interface.
2. **MCP as the API boundary** — all external interaction happens through MCP tools, resources, and prompts. The agent is an implementation detail behind the MCP server.
3. **Tools are atoms, agent is a molecule** — every internal agent capability (SQL generation, data profiling, schema search, visualization suggestion) is exposed as an independent MCP tool. The agent composes these tools; so can the client.
4. **Excel is not a DataFrame** — Excel files have fundamentally different semantics (formulas, merged cells, layouts). The Excel module has its own specialized tools that coexist with but differ from the SQL/DataFrame tools.
5. **Composition over monolith** — each concern (transport, tools, agent logic, data access, UI) is a separate package. No god-modules.
6. **Dynamic pipeline, not rigid modes** — the 5 thinking modes are plan TEMPLATES, not fixed subgraphs. The plan node generates a dynamic sequence of tool calls; the mode determines the scaffold complexity (single-pass vs checkpointed vs meta-loop). New tools can be added without changing the scaffold.

---

## 4. Data Source Abstraction Layer

### 4.1 DataSource Interface

All data sources implement a common interface for metadata/capabilities, while specialized interfaces handle source-specific operations.

```python
# mcpdb/sources/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SourceType(Enum):
    DATABASE = "database"
    CSV = "csv"
    EXCEL = "excel"


@dataclass
class ColumnInfo:
    name: str
    dtype: str
    nullable: bool = True
    description: str = ""


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo]
    row_count: int | None = None
    schema: str | None = None       # DB schema (e.g. "public")
    source_file: str | None = None  # File path for CSV/Excel
    sheet_name: str | None = None   # For Excel
    primary_keys: list[str] = field(default_factory=list)
    indexes: list[dict] = field(default_factory=list)


@dataclass
class SourceMetadata:
    """Unified metadata that every source must provide."""
    source_id: str                  # Unique ID within the session
    source_type: SourceType
    display_name: str               # Human-readable label
    tables: list[TableInfo]         # Queryable tables/datasets
    capabilities: set[str]          # {"sql", "python", "formulas", "cross_join", ...}
    raw_info: dict[str, Any] = field(default_factory=dict)  # Source-specific extras


class DataSource(ABC):
    """Base interface for all data sources."""

    @abstractmethod
    def get_metadata(self) -> SourceMetadata:
        """Return schema/structure metadata for the LLM context."""

    @abstractmethod
    def get_context_description(self) -> str:
        """Return a text description suitable for injection into LLM prompts."""

    def get_schema_json(self) -> str:
        """Return schema as JSON (for MCP resources). Default: JSON-serialize metadata."""
        return json.dumps(self.get_metadata().to_dict())

    def get_tables(self) -> list[TableInfo]:
        """Return table/sheet list. Default: extract from metadata."""
        return self.get_metadata().tables

    def get_relationships(self) -> list[dict]:
        """Return FK/inferred relationships. Default: extract from metadata FKs."""
        return []

    def render_erd(self) -> str:
        """Return Mermaid ER diagram string. Uses shared erd_generator."""
        from mcpdb.sources.erd_generator import generate_mermaid_erd
        return generate_mermaid_erd(self.get_tables(), self.get_relationships())

    @abstractmethod
    def close(self) -> None:
        """Release resources. Called by SessionManager on remove_source() and on session end.
        Must handle already-closed state gracefully (idempotent)."""

    @property
    @abstractmethod
    def source_type(self) -> SourceType:
        """Return the type of this source."""


class QueryableSource(DataSource):
    """Source that supports SQL-like querying (databases, CSV via DuckDB)."""

    @abstractmethod
    def execute_query(self, query: str, max_rows: int = 100) -> "pd.DataFrame":
        """Execute a SQL query and return results."""

    @abstractmethod
    def get_sample(self, table_name: str, limit: int = 5) -> "pd.DataFrame":
        """Return sample rows from a table/dataset."""


class SpreadsheetSource(DataSource):
    """Source that represents a workbook with sheets and cells (Excel)."""

    @abstractmethod
    def list_sheets(self) -> list[dict]:
        """List all sheets with metadata (name, dimensions, has_formulas)."""

    @abstractmethod
    def read_range(self, sheet: str, range_str: str | None = None,
                   include_formulas: bool = False) -> "CellGrid":
        """Read a range of cells with optional formula extraction."""

    @abstractmethod
    def get_sheet_structure(self, sheet: str) -> "SheetStructure":
        """Analyze sheet layout: detect tables, headers, merged regions, etc."""

    @abstractmethod
    def extract_table(self, sheet: str, table_range: str) -> "pd.DataFrame":
        """Extract a rectangular region as a DataFrame (best-effort)."""
```

### 4.2 Source Registry

```python
# mcpdb/sources/registry.py

class SourceRegistry:
    """Manages active data sources within a session.

    Thread-safe. Each source has a unique source_id.
    Supports:
      - Adding/removing sources dynamically
      - Listing all active sources with metadata
      - Looking up sources by ID
      - Building combined context for LLM prompts
    """

    def add_source(self, source: DataSource) -> str: ...
    def remove_source(self, source_id: str) -> None: ...
    def get_source(self, source_id: str) -> DataSource: ...
    def list_sources(self) -> list[SourceMetadata]: ...
    def get_combined_context(self) -> str: ...
    def get_queryable_sources(self) -> list[QueryableSource]: ...
    def get_spreadsheet_sources(self) -> list[SpreadsheetSource]: ...
```

---

## 5. Database Source Module

### 5.1 Overview

Carries forward the proven dialect system from dbtalk. Each database gets one dialect file implementing `DatabaseDialect`.

### 5.2 Package Structure

```
mcpdb/sources/database/
├── __init__.py              # Factory: create_db_source(connection_string) -> DatabaseSource
├── source.py                # DatabaseSource(QueryableSource) implementation
├── connector.py             # Connection management, retry, pooling (from dbtalk core/database.py)
├── schema_explorer.py       # Schema introspection, statistics (from dbtalk core/schema_explorer.py)
├── query_optimizer.py       # Sampling, chunking, cost estimation (from dbtalk core/query_optimizer.py)
├── cost_estimator.py        # Query cost analysis (from dbtalk core/query_cost_estimator.py)
└── dialects/
    ├── __init__.py           # Dialect factory and registry
    ├── base.py               # DatabaseDialect ABC
    ├── postgresql.py
    ├── mysql.py
    ├── sqlite.py
    ├── mssql.py
    └── oracle.py
```

### 5.3 DatabaseSource Implementation

```python
class DatabaseSource(QueryableSource):
    """Wraps a SQL database as a DataSource.

    Initialization:
      1. Connect using SQLAlchemy with dialect-specific settings
      2. Introspect schema (tables, columns, types, PKs, FKs, indexes)
      3. Collect row counts and column statistics
      4. Build table size tags for cost-aware classification

    Query execution:
      - execute_query(sql, max_rows) -> DataFrame
      - Automatic retry on transient connection errors
      - Query timeout enforcement (dialect-specific)
      - Truncation tracking (df.attrs['truncated'])

    Optimization:
      - QueryOptimizer: detects expensive queries, applies sampling/chunking
      - CostEstimator: 3-layer cost analysis (regex → LLM → heuristic)
    """
```

### 5.4 Dialect Contract (carried from dbtalk)

Each dialect implements (ported from dbtalk + new methods marked with 🆕):
- `get_connect_args(connect_timeout, query_timeout) -> dict`
- `get_system_schemas() -> set[str]`
- `get_row_count_query(schema) -> str | None`
- `get_column_stats_query(schema, table) -> str | None`
- `get_index_details_query(schema, table) -> str | None`
- `add_limit(query, n) -> str`
- `add_random_limit(query, n) -> str`
- `add_sampling(query, table, row_count, sample_size) -> str`
- `get_sql_syntax_rules() -> str`
- `quote_identifier(name) -> str`
- `get_retryable_errors() -> list[str]`
- 🆕 `get_explain_prefix() -> str` — Returns the EXPLAIN command prefix for this dialect
- 🆕 `parse_explain_output(rows: list[dict]) -> ExplainResult` — Parse dialect-specific EXPLAIN output into a normalized structure
- 🆕 `cancel_query(connection) -> None` — Issue a dialect-specific query cancellation command (see Section 10.3)

### 5.5 EXPLAIN Plan Integration (new)

The system uses actual database EXPLAIN output for cost estimation, not just LLM heuristics.

**Dialect-specific EXPLAIN commands**:
| Dialect | EXPLAIN Prefix | Output Format |
|---------|---------------|---------------|
| PostgreSQL | `EXPLAIN (FORMAT JSON, ANALYZE false)` | JSON with estimated rows, cost, plan nodes |
| MySQL | `EXPLAIN FORMAT=JSON` | JSON with query_cost, rows_examined_per_scan |
| SQL Server | `SET SHOWPLAN_XML ON` (or `SET STATISTICS PROFILE ON`) | XML/tabular with EstimateRows, EstimateIO |
| Oracle | `EXPLAIN PLAN FOR` + `SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY)` | Text with Rows, Bytes, Cost |
| SQLite | `EXPLAIN QUERY PLAN` | Tabular (detail column describes scan type) |

**Normalized EXPLAIN result**:
```python
@dataclass
class ExplainResult:
    """Normalized output from any dialect's EXPLAIN."""
    estimated_rows: int | None        # Total rows the DB planner expects to process
    estimated_cost: float | None      # Planner cost units (dialect-specific, useful for relative comparison)
    scan_type: str                    # "seq_scan", "index_scan", "index_only_scan", "bitmap_scan"
    join_types: list[str]             # ["nested_loop", "hash_join", "merge_join"]
    uses_index: bool                  # Whether any index is used
    warnings: list[str]              # ["sequential scan on large_table (2.5M rows)", "nested loop join"]
    raw_plan: dict | str             # Original EXPLAIN output for LLM analysis
```

**Integration into cost estimation** (extends Section 9.6 `cost_check` node):

The 3-layer cost analysis becomes 4 layers:
- **Layer 0 (fast-path)**: Regex scan — unchanged
- **Layer 1 (EXPLAIN, new)**: Run `EXPLAIN` (not `EXPLAIN ANALYZE` — never executes the query) on each SQL step. Parse via `dialect.parse_explain_output()`. Flag queries with: seq scan on tables >100K rows, nested loop joins, estimated rows >1M, no index usage on filtered columns. If all steps are low-cost → `"not_required"`, skip LLM entirely.
- **Layer 2 (LLM)**: If Layer 1 flags concerns, send EXPLAIN output + table sizes + schema to reasoning LLM for nuanced analysis. The LLM sees actual planner estimates, not just table row counts.
- **Layer 3 (heuristic fallback)**: Only used when both EXPLAIN and LLM fail.

**Why EXPLAIN but not EXPLAIN ANALYZE**: `EXPLAIN ANALYZE` actually executes the query, which defeats the purpose of pre-execution cost estimation. Plain `EXPLAIN` only asks the planner for its estimate without executing anything.

**Cardinality-aware planning**: Column statistics collected during initialization (`get_column_stats_query`) — including `n_distinct`, `null_frac`, and `avg_width` — are stored in `SourceMetadata.column_stats`. The planning node's prompt includes these stats for key columns so the LLM can make cardinality-aware decisions (e.g., "customer_id has 50K distinct values → GROUP BY customer_id produces ~50K rows → fits in memory").

---

## 6. CSV Source Module

### 6.1 Overview

CSV files are loaded into **DuckDB** in-memory, giving them full SQL query capabilities identical to databases. This means the same LangGraph subgraphs, tools, and prompts work for CSVs with zero special-casing in the agent logic.

### 6.2 Package Structure

```
mcpdb/sources/csv/
├── __init__.py           # Factory: create_csv_source(file_paths) -> CsvSource
├── source.py             # CsvSource(QueryableSource) implementation
├── loader.py             # CSV detection, encoding, parsing, multi-file loading
└── duckdb_backend.py     # DuckDB session management, table registration
```

### 6.3 CsvSource Implementation

```python
class CsvSource(QueryableSource):
    """Wraps one or more CSV files as SQL-queryable tables in DuckDB.

    Initialization flow:
      1. For each file path:
         a. Detect encoding (chardet/cchardet fallback)
         b. Detect delimiter (csv.Sniffer + heuristic for TSV, pipe, semicolon)
         c. Detect header row (first row analysis)
         d. Infer column types (DuckDB auto-detection + override hints)
         e. Load into DuckDB as a named table
      2. Table name = sanitized filename stem (e.g. "sales_2024.csv" -> "sales_2024")
         - Collision handling: append _2, _3, etc.
      3. Build SourceMetadata with all registered tables

    Multi-file:
      - Each CSV becomes a separate table in the same DuckDB session
      - Cross-file JOINs are fully supported via standard SQL
      - UNION operations across similar CSVs are natural

    Query execution:
      - execute_query(sql, max_rows) routes to DuckDB
      - DuckDB provides identical SQL semantics to PostgreSQL
      - Supports window functions, CTEs, aggregations, etc.
    """
```

### 6.4 CSV Loader Details

```python
@dataclass
class CsvLoadResult:
    table_name: str            # Registered table name in DuckDB
    file_path: str
    encoding: str              # Detected encoding (utf-8, latin-1, etc.)
    delimiter: str             # Detected delimiter
    has_header: bool
    row_count: int
    columns: list[ColumnInfo]
    load_warnings: list[str]   # Any issues during loading


class CsvLoader:
    """Handles CSV file detection and loading.

    Detection pipeline:
      1. Encoding: Try UTF-8 first, then chardet, then latin-1 fallback
      2. Delimiter: csv.Sniffer on first 10KB, fallback heuristic (comma > tab > semicolon > pipe)
      3. Header: Analyze first row - if all string-like and unique, treat as header
      4. Type inference: DuckDB auto-detection with sample_size=10000

    Robustness:
      - Handle BOM markers (UTF-8-BOM)
      - Handle inconsistent row lengths (pad shorter rows, warn)
      - Handle quoted fields with embedded delimiters/newlines
      - Handle files with comment lines (# or // prefixed)
      - Handle empty files gracefully
      - Configurable: user can override delimiter, encoding, header row
    """

    def load_file(self, path: str, conn: "duckdb.DuckDBPyConnection",
                  table_name: str | None = None,
                  encoding: str | None = None,
                  delimiter: str | None = None,
                  has_header: bool | None = None) -> CsvLoadResult: ...

    def load_files(self, paths: list[str], conn: "duckdb.DuckDBPyConnection"
                   ) -> list[CsvLoadResult]: ...
```

### 6.5 DuckDB Backend

```python
class DuckDBBackend:
    """Manages an in-memory DuckDB session for CSV querying.

    Responsibilities:
      - Create/destroy DuckDB connection
      - Register DataFrames/CSV files as tables
      - Execute SQL queries with timeout enforcement
      - Provide schema introspection (INFORMATION_SCHEMA)
      - Memory management: track loaded data size, warn on limits

    Configuration:
      - memory_limit: Maximum RAM for DuckDB (default: "2GB")
      - threads: Worker threads (default: CPU count)
    """

    def __init__(self, memory_limit: str = "2GB"): ...
    def register_csv(self, path: str, table_name: str, **kwargs) -> None: ...
    def register_dataframe(self, df: "pd.DataFrame", table_name: str) -> None: ...
    def execute(self, sql: str, max_rows: int = 100) -> "pd.DataFrame": ...
    def get_tables(self) -> list[TableInfo]: ...
    def close(self) -> None: ...
```

---

## 7. Excel Source Module

### 7.1 Design Philosophy — Two-Case Model

Excel data falls into exactly **two cases**. The system detects which case applies and handles each differently:

**Case 1: DataFrame-representable** — The sheet (or a region of it) is a clean rectangular table with a header row and typed columns. This is the common case for data-oriented Excel files.
- **Handling**: Extract to DataFrame → load into DuckDB → query with SQL, identical to CSV.
- **Detection**: Simple heuristics (header row of strings + consistent column types + no gaps).
- **Result**: Full SQL query capability, charting, aggregation — same as database/CSV sources.

**Case 2: Textual/non-rectangular** — The sheet contains scattered data, merged cells, formulas, notes, or irregular layout. This covers dashboards, reports, financial models, etc.
- **Handling**: Render as formatted text → pass to LLM as context. The LLM reads and reasons about it like a human would read a spreadsheet printout.
- **Detection**: Anything that fails Case 1 heuristics, or sheets with >20% merged cells, or sheets with formula-heavy regions.
- **Result**: LLM-powered analysis (explain formulas, summarize data, answer questions about the layout). No SQL — the LLM works directly with the text representation.

**A single sheet can contain both cases** — e.g., a dashboard with a clean data table in B3:G50 (Case 1) and summary KPIs with merged headers in A1:G2 (Case 2). The system extracts what it can and renders the rest as text.

**v1.0 scope**: Focus on Case 1 (DataFrame extraction) with basic Case 2 support (text rendering). Advanced Case 2 features (formula dependency graphs, formula cluster analysis) are deferred to v1.1.

### 7.2 Package Structure

```
mcpdb/sources/excel/
├── __init__.py              # Factory: create_excel_source(file_path) -> ExcelSource
├── source.py                # ExcelSource(SpreadsheetSource) implementation
├── workbook_reader.py       # openpyxl-based reading with formula + value access
├── structure_analyzer.py    # Sheet layout analysis, table detection, region classification
├── cell_grid.py             # CellGrid data structure (raw cell access)
├── formula_analyzer.py      # Formula parsing, dependency tracking, explanation
├── table_extractor.py       # Best-effort rectangular extraction to DataFrame
└── multi_workbook.py        # Multi-file Excel session management
```

### 7.3 Core Data Structures

```python
# mcpdb/sources/excel/cell_grid.py

@dataclass
class CellValue:
    """Represents a single Excel cell with all its properties."""
    row: int
    col: int
    value: Any                  # Computed value (what Excel shows)
    formula: str | None         # Formula text (e.g. "=SUM(A1:A10)") or None
    data_type: str              # "string", "number", "date", "boolean", "error", "empty"
    is_merged: bool             # Part of a merged region
    merge_master: tuple[int, int] | None  # (row, col) of merge origin
    number_format: str | None   # e.g. "#,##0.00", "mm/dd/yyyy"
    comment: str | None         # Cell comment/note


@dataclass
class MergedRegion:
    """A merged cell region."""
    min_row: int
    min_col: int
    max_row: int
    max_col: int
    value: Any                  # Value from the top-left cell


@dataclass
class CellGrid:
    """2D grid of CellValue objects with utilities.

    This is the primary data structure for non-rectangular Excel data.
    It preserves all cell properties including formulas and merges.
    """
    cells: list[list[CellValue]]
    merged_regions: list[MergedRegion]
    sheet_name: str
    range_str: str              # e.g. "A1:F20"

    def to_text(self, include_formulas: bool = False) -> str:
        """Render as aligned text table for LLM consumption."""

    def to_dict(self) -> list[list[dict]]:
        """Serialize for JSON transport."""

    def get_cell(self, row: int, col: int) -> CellValue: ...

    def get_formulas(self) -> list[tuple[str, str]]:
        """Return list of (cell_ref, formula) pairs."""


@dataclass
class DetectedTable:
    """A rectangular table region detected within a sheet (Case 1)."""
    range_str: str              # e.g. "B3:G15"
    header_row: int
    headers: list[str]
    data_rows: int
    col_types: list[str]        # Dominant type per column: "string", "number", "date", etc.


@dataclass
class TextRegion:
    """A non-rectangular region rendered as text for LLM (Case 2)."""
    range_str: str              # e.g. "A1:G2"
    text_repr: str              # Formatted text rendering of the region
    has_formulas: bool
    has_merged_cells: bool
    description: str            # Auto-generated: "Summary header with 3 merged KPI cells"


@dataclass
class SheetStructure:
    """Analyzed structure of a single Excel sheet — two-case classification."""
    name: str
    dimensions: str             # e.g. "A1:Z100"
    row_count: int
    col_count: int
    tables: list[DetectedTable]        # Case 1: DataFrame-representable regions
    text_regions: list[TextRegion]     # Case 2: Non-rectangular regions (rendered as text)
    merged_regions: list[MergedRegion]
    has_formulas: bool
    formula_count: int
    summary: str                # Human-readable summary for LLM
```

### 7.4 ExcelSource Implementation

```python
class ExcelSource(SpreadsheetSource):
    """Wraps an Excel workbook (.xlsx/.xlsm) as a data source.
    NOTE: .xls (legacy binary format) is NOT supported — openpyxl only handles
    .xlsx/.xlsm. Users with .xls files must convert to .xlsx first.

    Initialization (two-case classification):
      1. Open workbook with openpyxl (data_only=False to get formulas)
      2. Also open with data_only=True to get computed values
      3. For each sheet, run StructureAnalyzer:
         a. Detect rectangular table regions (Case 1) → DetectedTable
         b. Everything else → TextRegion (Case 2), rendered as formatted text
         c. Build SheetStructure with both lists
      4. For each DetectedTable: extract to DataFrame, load into DuckDB
         (same as CSV — gives full SQL capability)
      5. Build SourceMetadata

    Case 1 (DataFrame tables):
      - Extracted to DuckDB automatically during init
      - Named as "{workbook}_{sheet}_{range}" (e.g. "budget_Sales_B3_G50")
      - Queryable via SQL, same as CSV tables
      - execute_query() works on these tables

    Case 2 (text regions):
      - Rendered as formatted text via CellGrid.to_text()
      - Passed to LLM as context (not queryable via SQL)
      - read_range() returns CellGrid for any arbitrary range
      - LLM reasons about the text directly

    Formula support (basic for v1.0):
      - Formulas are visible in CellGrid (formula field on CellValue)
      - explain_formula() gives natural-language explanation
      - Full dependency graph and cluster analysis deferred to v1.1
    """
```

### 7.5 Structure Analyzer

```python
class SheetStructureAnalyzer:
    """Classifies each region of a sheet as Case 1 (table) or Case 2 (text).

    Algorithm (simple and conservative):
      1. Scan all cells to build occupancy map (non-empty cells)
      2. Find contiguous rectangular blocks separated by empty rows/columns
      3. For each block, apply the **table test** (all must pass):
         a. First row is all strings (header candidates)
         b. At least 2 columns and 3+ data rows
         c. No merged cells within the block
         d. Each column has >80% values of a single type
         If passes → DetectedTable (Case 1)
         If fails  → TextRegion (Case 2), rendered via CellGrid.to_text()
      4. Any cells not covered by a detected block → TextRegion
      5. Generate human-readable summary

    Design principle: **conservative extraction**. If in doubt, classify as
    Case 2 (text). It's better for the LLM to see formatted text than for
    the system to extract a broken DataFrame. Users can always force
    extraction via the extract_excel_table tool on a specific range.
    """

    def analyze(self, sheet: "openpyxl.Worksheet",
                sheet_values: "openpyxl.Worksheet") -> SheetStructure: ...
```

### 7.6 Formula Analyzer

```python
class FormulaAnalyzer:
    """Parses and explains Excel formulas for LLM understanding.

    v1.0 capabilities (simple):
      - Parse formula references (A1, Sheet2!B3, named ranges)
      - Explain formula in natural language (via LLM with formula text as input)
      - List all formulas in a range/sheet

    v1.1 capabilities (deferred):
      - Build dependency graph (which cells feed into which)
      - Detect formula patterns (SUM, VLOOKUP, IF/THEN, pivot-like)
      - Map formula clusters (groups of similar formulas)
    """

    def parse_formula(self, formula: str) -> dict: ...
    def explain_formula(self, formula: str, cell_ref: str) -> str: ...
    def list_formulas(self, sheet: str, range_str: str | None = None) -> list[tuple[str, str]]: ...
```

### 7.7 Multi-Workbook Support

```python
class MultiWorkbookManager:
    """Manages multiple Excel files in a session.

    Each workbook gets a unique prefix for disambiguation:
      - "budget.xlsx" -> prefix "budget"
      - "actuals.xlsx" -> prefix "actuals"

    Cross-workbook references:
      - "budget::Sheet1!A1:C10" syntax for explicit references
      - LLM is informed about all loaded workbooks and their structures

    Use cases:
      - Compare budgets across years
      - Cross-reference lookup tables with data sheets
      - Merge data from multiple departmental spreadsheets
    """
```

---

## 8. Multi-File Session Manager

### 8.1 Overview

The **SessionManager** coordinates multiple data sources in a single conversation. A user might have a PostgreSQL database, two CSV files, and an Excel workbook all active simultaneously.

### 8.2 Implementation

```python
# mcpdb/session.py

class SessionManager:
    """Manages the lifecycle of a multi-source analysis session.

    Responsibilities:
      1. Track all active data sources (SourceRegistry)
      2. Build combined LLM context from all sources
      3. Route queries to the correct source
      4. Manage conversation history
      5. Coordinate cross-source operations
      6. Handle source lifecycle (connect, disconnect, reconnect)

    Cross-source queries:
      When a query spans multiple sources (e.g., "join the CSV sales data
      with the database customer table"), the session manager uses a
      **tiered federation strategy**:

      Strategy 1 — DuckDB native attachment (preferred for databases):
        DuckDB can attach to PostgreSQL, MySQL, SQLite natively via extensions
        (duckdb postgres_scanner, mysql_scanner, sqlite_scanner). When both sources
        are DuckDB-attachable, the query is executed entirely in DuckDB with
        zero data copying. This handles joins of any size efficiently.

      Strategy 2 — Pushdown + transfer (for non-attachable sources or mixed):
        a. Decompose the cross-source query into per-source subqueries
           (the planning node generates these — NOT the user's raw SQL)
        b. Each subquery is pushed down to its source with filters to minimize
           transfer (only rows matching join conditions are fetched)
        c. Results (DataFrames) are loaded into DuckDB's in-memory session
        d. DuckDB executes the final join/aggregation
        e. Memory guard: if estimated transfer exceeds 500MB, triggers cost gate

      Strategy 3 — Excel in cross-source:
        Excel data is extracted into a DataFrame via `extract_excel_table` first,
        then loaded into DuckDB. This only works for rectangular Excel regions.

      The `cross_source_query` MCP tool receives `source_mapping: dict[str, str]`
      where keys are table aliases used in the DuckDB query and values are
      `"source_id.table_name"` references. The session manager resolves each
      alias to the correct source and attachment method.

    Conversation history:
      - list[Message] with a sliding window: last 50 messages kept in full,
        older messages summarized by the fast LLM into a context block.
        This prevents context window overflow for long sessions.
      - History is NOT persisted across server restarts (stateless server).
        The experience system (Section 11) provides cross-session learning.

    State:
      - Active sources: dict[str, DataSource]
      - Conversation window: list[Message] (bounded, 50 messages + summary)
      - Experience system: per-source cache, templates, anti-patterns (Section 11)
      - Execution log: audit trail
    """

    def connect_database(self, connection_string: str, display_name: str = "") -> str: ...
    def load_csv(self, file_paths: list[str]) -> str: ...
    def load_excel(self, file_path: str) -> str: ...
    def remove_source(self, source_id: str) -> None: ...
    def list_sources(self) -> list[SourceMetadata]: ...
    def get_combined_context(self) -> str: ...
    def execute_cross_source_query(self, sql: str, source_ids: list[str]) -> "pd.DataFrame": ...
```

---

## 9. LangGraph Agent Orchestration

### 9.1 Overview — Five Thinking Modes

**IMPORTANT: Agent Mode is one of two usage patterns** (see Section 3.2). In **Tool Mode**, the client's LLM orchestrates MCP tools directly — the LangGraph agent is not involved. The agent orchestration described in this section powers **Agent Mode** (the `ask_question` tool) and can be thought of as a pre-built expert pipeline that composes the same MCP tools a client could call independently.

The agent has **five distinct thinking modes**, ordered from simplest to deepest. Each mode represents a different depth of reasoning, number of execution steps, and degree of self-reflection. The system auto-classifies every user question into the appropriate mode.

**Modes are plan templates, not rigid subgraphs**: Each mode defines a SCAFFOLD (the graph topology: which nodes exist, how they connect, what self-correction loops are available). Within that scaffold, the PLAN node dynamically generates the specific sequence of tool calls. The scaffold determines complexity class; the plan determines actual operations. Adding new MCP tools (e.g., `render_erd`, `profile_table`) to the system makes them available in plans across ALL modes — no scaffold changes needed.

| # | Mode | Label | Depth | Steps | Self-Correction | Key Feature |
|---|------|-------|-------|-------|-----------------|-------------|
| 1 | **Quick** | 💬 Context Chat | Shallowest | 0 | Escalation to Simple | No code execution — answers from schema context |
| 2 | **Simple** | ⚡ Quick Analysis | Standard | 1–5 | 1 replan | Plan → execute → validate → synthesize |
| 3 | **Optimization** | ⚠️ Heavy Query | Standard + cost gate | 1–10 | 0 replans (plan is rewritten by optimizer) | User-gated strategy selection for large tables |
| 4 | **Extended** | 🔬 Deep Analysis | Deep | 3–10 | 2 revisions + checkpoints | Periodic checkpoints, reflection before synthesis |
| 5 | **Deep Analysis** | 🧠 Research Mode | Deepest | Unlimited (3–8 investigations × N steps each) | Adaptive — adds/skips investigations | Meta-loop: blueprint → investigate → reason → synthesize |

**Critical distinction**: Modes 1–4 are implemented as **LangGraph subgraphs** inside the orchestrator. Mode 5 (Deep Analysis) is a **meta-loop that sits above the orchestrator** — it invokes the full agent graph multiple times (once per investigation), reasoning between invocations to adapt the research plan.

### 9.2 Agent State

```python
# mcpdb/agent/state.py

class AgentState(TypedDict):
    """Shared state for all subgraphs. Every field is used by at least one mode.

    Fields are grouped by which mode(s) use them. This makes it clear
    that simpler modes ignore fields they don't need.
    """

    # --- Conversation (ALL modes) ---
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # --- Source Context (ALL modes) ---
    source_context: str             # Combined description of all active sources
    active_source_ids: list[str]    # IDs of sources in this session
    source_capabilities: dict[str, set[str]]  # source_id -> {"sql", "formulas", ...}

    # --- Classification (ALL modes — set by classify node) ---
    query_mode: Literal["quick", "simple", "extended", "optimization_required"] | None
    target_sources: list[str]       # Which sources this query targets
    requires_cross_source: bool     # Needs data from multiple sources

    # --- Planning & Execution (Simple, Extended, Optimization) ---
    plan: dict | None               # {"analysis", "approach", "steps": [...], "current_step_index": int}
    thinking_steps: list[dict]      # [{timestamp, step_type, message, details}]
    execution_log: list[dict]       # [{step_number, code_type, code, time_ms, memory_delta_mb, status, result_preview}]
    artifacts: list[dict[str, Any]] # [{type, data, title, ...}]
    last_result: dict | None        # Last step result (DataFrame dict, CellGrid dict, etc.)

    # --- Debugging (Simple, Extended, Optimization) ---
    max_retries: int                # Max retry attempts per step (default: 3)
    current_error: dict | None      # {step_index, action, code, error, attempts}

    # --- Cost Gate (Simple, Extended, Optimization) ---
    optimization_state: str | None  # "not_required" | "recommended" | "necessary"
    cost_analysis: dict | None      # {total_estimated_rows, total_estimated_time_ms, max_risk_level, reason, ...}
    strategy_choice: str | None     # "SAMPLE" | "FULL" | "CANCEL" — set externally by user/UI

    # --- Validation (Quick → uses validation_result for escalation;
    #                  Simple → adequate/inadequate;
    #                  Extended → continue/revise/done via checkpoint) ---
    validation_result: str | None   # "complete" | "needs_data" | "adequate" | "inadequate" | "continue" | "revise" | "done"
    validation_reason: str | None   # Why validation failed (for replan/revise context)
    replan_count: int               # Number of replans done (max 1 for Simple, 2 for Extended)

    # --- Extended mode only ---
    checkpoint_results: list[dict]  # [{after_step, decision, reason}]
    reflection: str | None          # Holistic reflection text before synthesis
```

**State lifecycle across modes:**

| State field | Quick | Simple | Extended | Optimization |
|-------------|-------|--------|----------|-------------|
| `messages` | Read + write answer | Read + write synthesis | Read + write synthesis | Read + write synthesis |
| `query_mode` | Set by classify | Set by classify | Set by classify | Set by classify |
| `plan` | Never set | Set by plan node | Set by plan node | Set by plan node |
| `current_error` | Never set | Set/cleared by execute/debug | Set/cleared by execute/debug | Set/cleared by execute/debug |
| `optimization_state` | Never set | Set by cost_check | Set by cost_check | Set by cost_check |
| `strategy_choice` | Never set | Never set (goes to strategy_gate→END) | Never set (goes to strategy_gate→END) | Set externally by user after first run |
| `validation_result` | "complete" or "needs_data" | "adequate" or "inadequate" | "continue", "revise", or "done" | "adequate" (always, no replan) |
| `replan_count` | N/A | 0→1 (max 1 replan) | 0→1→2 (max 2 revisions) | N/A (optimize_plan rewrites instead) |
| `checkpoint_results` | N/A | N/A | Accumulated every 3 steps | N/A |
| `reflection` | N/A | N/A | Set before synthesis | N/A |

### 9.3 Orchestrator Graph Topology

```
                         ┌─────────────┐
                         │  __start__  │
                         └──────┬──────┘
                                │
                         ┌──────▼──────┐
                         │  classify   │  ← Determines query_mode
                         └──────┬──────┘
                                │
            ┌───────────────────┼───────────────────┐────────────────────┐
            │                   │                   │                    │
     ┌──────▼──────┐     ┌──────▼──────┐     ┌──────▼──────┐     ┌──────▼──────┐
     │   quick     │     │   simple    │     │  extended   │     │optimization │
     │  subgraph   │     │  subgraph   │     │  subgraph   │     │  subgraph   │
     └──────┬──────┘     └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
            │                   │                   │                    │
            ├──(escalate)──────→│                   │                    │
            │                   │                   │                    │
            ▼                   ▼                   ▼                    ▼
          END                 END                 END                  END


     Deep Analysis meta-loop (Mode 5) sits ABOVE this graph:
     ┌──────────────────────────────────────────────────────────────────┐
     │  create_blueprint → for each investigation:                     │
     │    invoke orchestrator graph → reason_about_results → adapt     │
     │  → synthesize_deep_analysis                                     │
     └──────────────────────────────────────────────────────────────────┘
```

### 9.4 The Classify Node

The classify node is the entry point for every user question. It determines which subgraph handles the question.

**Input**: User question + source context + conversation history + table size context.

**Output**: `query_mode` field set to one of `"quick"`, `"simple"`, `"extended"`, `"optimization_required"`. Uses **structured JSON output** (not string parsing).

**Additional outputs** (multi-source extensions):
- `target_sources`: Which data sources are needed
- `requires_cross_source`: Whether the question needs data from multiple sources
- `key_entities`: Tables, columns, sheets mentioned or implied — used for **schema subsetting** (see planning node below) so that only relevant schema is sent to subsequent LLM calls

**Classification rules** (injected into LLM prompt):

| Mode | When to use | When NOT to use |
|------|------------|-----------------|
| `quick` | Schema questions ("What tables exist?"), questions about previous results, pure clarification | ANY question needing actual data values, counts, aggregations |
| `simple` | Questions needing 1–5 execution steps on small/medium tables (<1M rows); single visualization; strategy resume (when `strategy_choice` is pre-set on state) | Questions explicitly requesting comprehensive/full analysis; large table operations without narrow filters |
| `extended` | Full EDA, root cause analysis, multi-angle investigations, multiple visualizations, keywords: "comprehensive", "detailed", "full analysis", "investigate", "dashboard" | Simple single-question queries; schema-only questions |
| `optimization_required` | Unfiltered aggregations on tables >1M rows; full scans/GROUP BY on LARGE/VERY_LARGE tables; JOINs between large tables without narrow WHERE | Queries with narrow indexed filters; queries with LIMIT; only small tables involved; user already specified sampling/subsetting |

**Strategy resume**: When the user submits a strategy choice via `submit_strategy` tool (Section 12.3 Category 6), the session sets `strategy_choice` on the agent state and re-invokes the orchestrator. The classify node detects `strategy_choice is not None` and routes directly to the optimization subgraph's execute phase, bypassing re-classification. (NOTE: this is a state-based protocol — not legacy string prefix hacking.)

**Fallback**: If LLM classification fails, defaults to `simple`.

### 9.5 Mode 1: Quick — 💬 Context Chat

**Purpose**: Answer questions using only schema knowledge and conversation history. Zero code execution.

**When selected**: Schema structure questions, questions about previously displayed results, metadata questions.

**Graph topology**:
```
context_answer ──→ validate_answer ──→ END
       │                  │
       │ (self-detected    │ (validation says
       │  needs_data)      │  needs_data)
       └──────────────────→└──────────────────→ END
                                                  ↑
                                           validation_result = "needs_data"
                                           (orchestrator escalates to Simple)
```

**Node details**:

1. **`context_answer`** — Invokes the reasoning LLM with:
   - Full database/source schema text
   - Table size context (row counts, size tags)
   - Conversation history (all messages)
   - The user's question
   - Instruction to respond with **structured JSON output** `{"action": "answer", "text": "..."}` or `{"action": "escalate", "reason": "needs data values"}`.

   **Outputs**:
   - **Happy path**: Sets `messages` with the AI answer, routes to `validate_answer`.
   - **Self-detected escalation**: If LLM returns `{"action": "escalate"}`, sets `validation_result = "needs_data"` and `query_mode = "simple"`, skips validation, goes to END. (NOTE: uses structured JSON output — not legacy sentinel strings.)
   - **LLM failure**: Escalates to Simple (safer than returning nothing).

2. **`validate_answer`** — Quality check on the context-only answer. Invokes the reasoning LLM to determine if the answer is sufficient (`"complete"`) or requires actual data (`"needs_data"`).
   - **Validation rules** (injected into LLM prompt): Schema structure, table names, column names, relationships, indexes, data types, and approximate row counts CAN be answered from context alone. Only flag `needs_data` if the question specifically asks for data values, counts, aggregations, or record contents.
   - **Bias**: When in doubt, says `"complete"` — it's better to provide a schema-based answer than escalate unnecessarily.

**Escalation mechanism**: After the Quick subgraph completes, the **orchestrator** checks `validation_result`. If `"needs_data"`, it routes to the Simple subgraph as a follow-up (the conversation state carries over).

**Key properties**:
- No plan is created
- No code is executed
- No artifacts are generated
- Fastest mode (single LLM call + optional validation call)
- Can escalate to Simple but never to Extended or Optimization

### 9.6 Mode 2: Simple — ⚡ Quick Analysis

**Purpose**: Execute a focused 1–5 step plan (SQL queries, Python analysis, Excel reads) to answer a data question.

**When selected**: Default for most data questions. Single-table queries, basic aggregations, single visualizations, cross-source joins.

**Graph topology**:
```
plan ──→ cost_check ──(safe)──→ execute ⟷ debug ──→ validate_result ──(adequate)──→ synthesize ──→ END
  │           │                                            │
  │           └──(expensive)──→ strategy_gate ──→ END      └──(inadequate)──→ replan ──→ execute ──→ ...
  │
  └──(empty plan)──→ synthesize ──→ END
```

**Node details**:

1. **`plan`** (shared factory: `make_planning_node`) — Generates an execution plan via the reasoning LLM.
   - **Input context**: **Relevant** source schemas (NOT the full schema dump — the classifier's `target_sources` and `key_entities` are used to subset the schema to only tables/columns likely relevant to the question; for 50+ table databases this saves significant tokens), user question, execution mode (`"simple"`), mode guidance ("focused plan with 1–5 steps, focus on ONE outcome"), dialect-specific SQL syntax rules, experience templates (up to 3 similar successful queries from per-source experience store — see Section 11.6), anti-patterns (known failures for referenced tables — see Section 11.7), strategy history (previously successful optimization patterns).
   - **Schema subsetting**: The classify node outputs `key_entities` (tables/columns mentioned or implied by the question). The planning node uses `search_schema` internally to expand these to include related tables (via FK relationships, name similarity) and provides ONLY this subset + a brief summary of remaining tables. This replaces the dbtalk pattern of dumping the entire schema into every prompt.
   - **Output**: `plan` dict with structure:
     ```json
     {
       "analysis": "What the user wants",
       "approach": "How we'll get it",
       "target_sources": ["source_id_1"],
       "current_step_index": 0,
       "steps": [
         {
           "step_number": 1,
           "action": "sql",
           "source_id": "db_1",
           "description": "Get top customers by revenue",
           "code": "SELECT ...",
           "status": "pending",
           "attempts": 0
         }
       ]
     }
     ```
   - **Fallback**: If LLM fails, creates a single-step fallback plan.
   - **Empty plan guard**: If plan has no steps, routes directly to `synthesize`.

2. **`cost_check`** (shared factory: `make_cost_check_node`) — Four-layer cost analysis (see also Section 5.5 for EXPLAIN integration):
   - **Layer 0 (fast-path)**: Regex scan of plan + user question for explicit sampling/limiting patterns (`TABLESAMPLE`, `LIMIT N`, `sample of N rows`). If found with N < 500,000 → `optimization_state = "not_required"`, skip gate.
   - **Layer 1 (EXPLAIN plan)**: Run `EXPLAIN` (not ANALYZE) on each SQL step via `dialect.get_explain_prefix()`. Parse output via `dialect.parse_explain_output()`. Flag queries with: seq scan on tables >100K rows, nested loop joins, estimated rows >1M, no index usage on filtered columns. If all steps are low-cost → `"not_required"`, skip LLM entirely. EXPLAIN output is attached to the step for use by downstream nodes (optimize_plan, debug).
   - **Layer 2 (LLM, enhanced)**: If Layer 1 flags concerns, sends plan steps + **EXPLAIN output** + table sizes + column statistics to reasoning LLM. LLM now sees actual planner estimates and can make nuanced decisions. Returns `{"optimization_needed": true/false, "level": "recommended"|"necessary", ...}`.
   - **Layer 3 (heuristic fallback)**: Only used when both EXPLAIN and LLM fail. Uses `QueryCostEstimator` to estimate rows scanned, execution time, and risk level based on table sizes and query patterns.

   **Routing after cost_check**:
   - `optimization_state == "not_required"` → `execute`
   - `optimization_state in ("recommended", "necessary")` → `strategy_gate`

3. **`strategy_gate`** (shared factory: `make_strategy_gate_node`) — Generates a user-facing explanation of why the query is expensive (via LLM), emits a `strategy_request` callback event, and **suspends** the graph (see state machine below).

   **Strategy Gate State Machine** (critical — this is NOT a simple graph termination):

   ```
   ask_question("expensive query")
     ├── classify → plan → cost_check → strategy_gate
     │     strategy_gate:
     │       1. Saves full AgentState snapshot to SessionManager.pending_strategies[session_id]
     │       2. Emits strategy_request event via CallbackManager
     │       3. Returns ask_question tool response: {status: "awaiting_strategy", session_id, strategies: [...]}
     │       4. Graph exits (→ END) — but state is preserved in SessionManager
     │
     └── [Client shows strategy buttons to user]

   submit_strategy(session_id, strategy="SAMPLE")
     ├── SessionManager retrieves saved AgentState from pending_strategies[session_id]
     ├── Sets strategy_choice = "SAMPLE" on the restored state
     ├── Deletes pending_strategies[session_id] (one-shot — can't resubmit)
     ├── Re-invokes the orchestrator graph with the restored state
     │     classify node sees strategy_choice is set → routes to optimization subgraph
     │     cost_check sees strategy_choice is set → returns "not_required"
     │     optimize_plan rewrites SQL per strategy → execute → ...
     └── Returns: streaming events from Phase 2 execution
   ```

   **State preservation details**:
   - `SessionManager.pending_strategies: dict[str, AgentState]` — maps session_id to frozen state
   - TTL: 10 minutes. If user doesn't respond within 10 minutes, the pending strategy is evicted and `submit_strategy` returns an error ("Strategy request expired, please re-ask the question")
   - Only ONE pending strategy per session. A new `ask_question` call while a strategy is pending cancels the pending strategy
   - The saved state includes: `plan`, `cost_analysis`, `source_context`, `messages`, `target_sources` — everything needed to resume without re-planning

4. **`execute`** (shared factory: `make_execute_step_node`) — Executes the current plan step (identified by `plan.current_step_index`).
   - **Action dispatch** (source-aware):
     | Action | Behavior |
     |--------|----------|
     | `sql` | Execute SQL via `DatabaseSource.execute_query()` or `CsvSource.execute_query()`. Result → DataFrame → artifact. Stores DataFrame in `last_dataframe` for Python follow-up. |
     | `python` | Execute code in sandbox with pre-injected `df`, `pd`, `np`, `plt`, `sns`, `db_query()`. Captures figures, DataFrames, scalars. |
     | `excel_read` | Read cell range via `ExcelSource.read_range()` → CellGrid artifact. |
     | `excel_structure` | Analyze sheet layout via `ExcelSource.get_sheet_structure()`. |
     | `excel_formula` | Explain formula via `FormulaAnalyzer.explain_formula()`. |
     | `excel_extract` | Extract rectangular table via `ExcelSource.extract_table()` → DataFrame. |
     | `cross_query` | Fetch data from multiple sources into DuckDB, execute join query. |
     | `schema` | Return schema text for the targeted source (maps to `get_source_schema` tool). |
     | `sample` | Return first N rows from a table (maps to `get_table_sample` tool). |
     | `profile` | Profile a table's data distribution (maps to `profile_table` tool). |
     | `erd` | Generate Mermaid ERD for relevant tables (maps to `render_erd` tool). |
     | `generate_sql` | LLM generates SQL from natural language (maps to `generate_sql` tool). |
     | `visualize` | LLM suggests + generates visualization code (maps to `suggest_visualization` tool). |

     NOTE: Each action maps to an MCP tool from Section 12.3. The plan node's LLM can use ANY tool in its plan — the list above is not exhaustive. New tools added to the MCP server automatically become available as plan actions.

   - **On success**: Increments `plan.current_step_index`, clears `current_error`, stores result on the step.
   - **On error**: Sets `current_error = {step_index, action, code, error, attempts}`, does NOT increment index.
   - **Metrics**: Records `time_ms`, `memory_delta_mb` per step.

   **Routing after execute**:
   - `current_error` is set → `debug`
   - `current_step_index < len(steps)` → `execute` (next step)
   - All steps done → `validate_result`

5. **`debug`** (shared factory: `make_debug_node`) — Fixes failed code with LLM assistance.
   - If `attempts >= max_retries` (default 3): marks step as `"failed"`, advances `current_step_index`, clears error. The step is skipped.
   - Otherwise: queries experience store for similar error fixes (see Section 11.6 `retrieve_for_debugging`), sends error + original code + schema + known fixes to reasoning LLM, gets corrected code. Replaces step's `code` field, resets step to `"pending"`, clears `current_error`. Records the failure and fix via `ExperienceRecorder`.

   **Routing after debug**:
   - More steps remaining → `execute`
   - All steps done → `validate_result`

6. **`validate_result`** (from `validators.py`) — Checks whether execution results actually answer the user's question.
   - **Skip condition**: If `replan_count >= 1`, automatically returns `"adequate"` (prevents infinite replan loops).
   - **LLM evaluation**: Sends user question + all step results to reasoning LLM. Returns `"adequate"` or `{"result": "inadequate", "reason": "..."}`.
   - **LLM failure**: Treats as `"adequate"` (don't replan on validation errors).

   **Routing after validate_result**:
   - `"adequate"` → `synthesize`
   - `"inadequate"` → `replan`

7. **`replan`** (from `validators.py`) — Creates a corrected plan based on validation feedback.
   - Sends: original question + previous results + validation reason + full planning prompt to reasoning LLM.
   - Replaces the entire `plan` with the new plan. Increments `replan_count`. Resets `current_error` and `validation_result`.
   - Routes to `execute` to run the corrected plan.
   - **Max 1 replan** in Simple mode (`replan_count >= 1` → validate_result auto-approves).

8. **`synthesize`** (shared factory: `make_synthesize_node`) — Generates the final user-facing response.
   - Uses the **fast LLM** (not reasoning model) for speed.
   - Sends: user question + all step results (success and failure).
   - Prompt instructions: "Directly answer the question, explain key findings, highlight patterns, use markdown. Do NOT just repeat raw data — interpret and explain."
   - Sets `messages` with the AI response.

**Key properties**:
- Creates a plan, executes it, validates, optionally replans once
- Cost gate can block execution for expensive queries (user must choose strategy)
- All step types supported (SQL, Python, Excel, cross-source)
- Uses fast LLM for synthesis (speed), reasoning LLM for everything else (quality)
- Max 1 replan, max 3 retries per step

### 9.7 Mode 3: Optimization — ⚠️ Heavy Query

**Purpose**: Handle queries on very large tables (>1M rows) that would timeout without optimization. Extends Simple with a plan-rewriting phase.

**When selected**: Unfiltered aggregations on LARGE/VERY_LARGE tables, full scans without narrow WHERE, JOINs between large tables.

**Graph topology**:
```
plan ──→ cost_check ──(safe)──→ execute ⟷ debug ──→ validate_result ──→ synthesize ──→ END
  │           │
  │           └──(expensive)──→ strategy_gate ──→ END  [User sees strategy buttons]
  │
  └──(empty plan)──→ synthesize ──→ END


SECOND RUN (after user submits strategy via submit_strategy tool):
  classify ──(strategy_choice set on state → skip classification)──→ optimization subgraph
    plan ──→ cost_check ──(skipped: strategy_choice set)──→ optimize_plan ──(CANCEL)──→ END
                                                                          ──(SAMPLE/FULL)──→ execute ⟷ debug ──→ validate ──→ synthesize ──→ END
```

**Unique node: `optimize_plan`** — Rewrites the plan's SQL queries using the chosen strategy.

- **`CANCEL`**: Emits cancellation message, routes to END.
- **`FULL`**: Keeps original plan unchanged (but will use chunked execution if needed).
- **`SAMPLE`**: Invokes reasoning LLM to rewrite all queries with sampling:
  - PostgreSQL: `TABLESAMPLE SYSTEM(percentage)` or `random()` filters
  - SQL Server: `TABLESAMPLE (percent PERCENT)`
  - MySQL/SQLite: `ORDER BY RAND()/RANDOM() LIMIT N`
  - Notes in results that values are approximate (based on X% sample)
  - LLM receives: original plan steps, strategy instructions, schema, table sizes.
  - Replaces `plan.steps` with optimized versions.

**Key differences from Simple**:
- Classification routes here instead of Simple when large tables are involved
- Has `optimize_plan` node that rewrites SQL for the chosen strategy
- Synthesis includes strategy metadata (e.g., "results are approximate, based on a sample")
- No replan loop (validate_result always routes to synthesize)
- The two-phase UX: first run creates plan → cost gate blocks → user picks strategy → second run executes with optimized plan

**Two-phase execution detail** (see Strategy Gate State Machine in Section 9.6, node 3):
1. **Phase 1** (first `ask_question` call): `plan → cost_check → strategy_gate → END`. The `ask_question` tool response returns `{status: "awaiting_strategy", session_id, strategies: [...], cost_analysis: {...}}`. Full `AgentState` is saved in `SessionManager.pending_strategies[session_id]`. The client renders strategy buttons.
2. **Phase 2** (user calls `submit_strategy(session_id, strategy)` MCP tool): The saved `AgentState` is restored from `pending_strategies`, `strategy_choice` is set, and the orchestrator graph is re-invoked with the restored state. The classify node detects `strategy_choice is not None` and routes to the optimization subgraph. `cost_check` sees `strategy_choice` is set → returns `"not_required"`. The `optimize_plan` node rewrites SQL. Execution proceeds with full streaming events.

**Timeout**: If the user doesn't call `submit_strategy` within 10 minutes, the saved state is evicted. The user must re-ask the question.

### 9.8 Mode 4: Extended — 🔬 Deep Analysis

**Purpose**: Comprehensive multi-step analysis with periodic self-assessment and course correction. For full EDA, root cause analysis, multi-angle investigations.

**When selected**: Keywords like "comprehensive", "detailed", "full analysis", "investigate", "research", "dashboard". Questions requiring 3–10 steps and multiple visualizations.

**Graph topology**:
```
plan ──→ cost_check ──(safe)──→ execute ⟷ debug ──→ checkpoint ──(continue)──→ execute (next steps)
  │           │                                         │              │
  │           │                                         │              └──(all steps done)──→ reflect ──→ synthesize ──→ END
  │           │                                         │
  │           │                                         ├──(revise)──→ revise_plan ──→ execute
  │           │                                         │
  │           │                                         └──(done)──→ reflect ──→ synthesize ──→ END
  │           │
  │           └──(expensive)──→ strategy_gate ──→ END
  │
  └──(empty plan)──→ synthesize ──→ END
```

**Unique nodes**:

1. **`checkpoint`** — Reviews progress every N completed steps (default: `CHECKPOINT_EVERY_N_STEPS = 3`).
   - **Trigger conditions**: Fires when `current_step_index > 0` AND `current_step_index % 3 == 0` AND remaining steps > 0. Also fires when all steps are done.
   - **LLM evaluation**: Sends completed step results + remaining step descriptions to reasoning LLM.
   - **Three possible decisions**:
     - `"continue"`: Remaining steps are fine, proceed as planned. Routes to `execute` if steps remain, `reflect` if done.
     - `"revise"`: Something needs to change in remaining steps. Only allowed if `replan_count < 2`. Routes to `revise_plan`.
     - `"done"`: Enough data has been collected to answer the question early. Routes to `reflect`.
   - **Checkpoint results** are accumulated in `checkpoint_results` list for the reflection phase.

2. **`revise_plan`** — Modifies remaining steps based on checkpoint feedback (different from Simple's `replan` which replaces the entire plan).
   - **Keeps completed steps** intact. Only generates new remaining steps starting from `current_step_index + 1`.
   - Increments `replan_count`. Max 2 revisions in Extended mode.
   - Routes to `execute` to continue with revised steps.

3. **`reflect`** — Holistic review of all findings before synthesis. This is Extended's key differentiator.
   - **LLM prompt**: "Do a final reflection on a comprehensive data analysis before writing the report."
   - **Output structure** requested:
     - Key Findings: Main answers/insights
     - Patterns: Trends or correlations
     - Data Quality: Missing data, failures, caveats
     - Narrative: Overall story the data tells
   - Sets `reflection` field, which is passed to the extended synthesis node.

4. **`synthesize` (extended variant)** — Enhanced synthesis that uses the reflection output.
   - Uses the **reasoning LLM** (not fast LLM — more thorough for comprehensive reports).
   - Prompt: "Write a comprehensive analysis report based on the data exploration."
   - Includes both step results AND the reflection text.
   - Produces a professional analysis report with: executive summary, detailed findings, patterns/trends, caveats.

**Key differences from Simple**:
- Mode guidance allows 3–10 steps (vs. 1–5)
- Checkpoint node replaces validate_result — periodic mid-execution review, not just end-of-execution validation
- Can revise (not fully replan) remaining steps up to 2 times
- Reflect node provides a meta-analysis before synthesis
- Uses reasoning LLM for synthesis (not fast LLM) — quality over speed
- No replan node (uses revise_plan instead, which preserves completed work)

### 9.9 Mode 5: Deep Analysis — 🧠 Research Mode (Meta-Loop)

**Purpose**: The most thorough analysis mode. Creates a multi-investigation research blueprint, executes each investigation independently (using the orchestrator graph), reasons about results between investigations, and adaptively modifies the research plan. Produces a comprehensive research report.

**When selected**: User explicitly enables "Deep Analysis" mode (toggle in UI or `deep_analysis=true` parameter in `ask_question` MCP tool). Not auto-selected by the classifier.

**Architecture**: This is NOT a LangGraph subgraph. It is a **Python meta-loop** that invokes the orchestrator graph multiple times.

**Flow**:
```
┌─────────────────────────────────────────────────────────────────────────┐
│                      DEEP ANALYSIS META-LOOP                           │
│                                                                        │
│  ┌─────────────────────┐                                               │
│  │  create_blueprint   │ ← LLM creates research agenda (3-8           │
│  │                     │   investigations) from user question          │
│  └──────────┬──────────┘                                               │
│             │                                                          │
│             ▼                                                          │
│  ┌─────────────────────┐                                               │
│  │  get_next_pending   │ ← Find next pending investigation             │
│  │  investigation      │                                               │
│  └──────────┬──────────┘                                               │
│             │                                                          │
│             │ (none left) ──────────────────────────────────────┐       │
│             │                                                  │       │
│             ▼                                                  │       │
│  ┌─────────────────────┐                                       │       │
│  │  invoke orchestrator│ ← Run full agent graph for THIS       │       │
│  │  graph with         │   investigation's question             │       │
│  │  investigation.     │   (classify → subgraph → result)      │       │
│  │  question           │                                       │       │
│  └──────────┬──────────┘                                       │       │
│             │                                                  │       │
│             ▼                                                  │       │
│  ┌─────────────────────┐                                       │       │
│  │  reason_about_      │ ← LLM evaluates: What did we learn?  │       │
│  │  results            │   Is goal reached? Skip any remaining?│       │
│  │                     │   Add new investigations?             │       │
│  └──────────┬──────────┘                                       │       │
│             │                                                  │       │
│             │ is_goal_reached=true ─────────────────────────┐  │       │
│             │                                               │  │       │
│             │ skip_indices → mark investigations as skipped  │  │       │
│             │ new_investigations → append to blueprint       │  │       │
│             │                                               │  │       │
│             └──────────→ (loop back to get_next_pending)    │  │       │
│                                                             │  │       │
│                                                             ▼  ▼       │
│                                               ┌─────────────────────┐  │
│                                               │  synthesize_deep_   │  │
│                                               │  analysis           │  │
│                                               └─────────────────────┘  │
│                                                                        │
└─────────────────────────────────────────────────────────────────────────┘
```

**Data structures**:

```python
@dataclass
class Investigation:
    index: int
    question: str           # Self-contained question for the orchestrator
    rationale: str          # Why this investigation matters
    status: str             # "pending" | "running" | "completed" | "skipped"
    result_summary: str     # Summary from the orchestrator's response
    key_findings: list[str] # Extracted findings

@dataclass
class Blueprint:
    original_question: str
    goal: str               # One-sentence description of overall goal
    investigations: list[Investigation]
    completed_count: int
    max_iterations: int     # Safety limit (default: 10 — caps total LLM calls at ~80)
    is_complete: bool
    completion_reason: str  # "all_done" | "goal_reached" | "stopped" | "max_iterations"

@dataclass
class MultistepState:
    active: bool
    blueprint: Blueprint
    current_index: int
    iteration_count: int
    stop_requested: bool    # User can stop mid-analysis
    accumulated_findings: list[dict]
    start_time: float
```

**Phase details**:

1. **`create_blueprint`** — LLM generates a research agenda.
   - Input: User question, database schema, conversation context.
   - Output: Blueprint with 3–8 investigations, ordered from most essential to least essential.
   - Each investigation is a self-contained question that can be answered independently by the orchestrator.
   - Example: User asks "Why is our loss ratio increasing?" → Blueprint:
     1. "What is the loss ratio trend over the past 24 months?"
     2. "Which product lines have the highest loss ratios?"
     3. "Has claims frequency or severity changed?"
     4. "Are there geographic patterns in high-loss areas?"
     5. "How do our rates compare to loss trends?"

2. **`invoke orchestrator`** — The investigation question is sent as a user message to the full orchestrator graph (classify → subgraph → result). The orchestrator doesn't know it's being called from a meta-loop — it treats it as a normal question.

3. **`reason_about_results`** — After each investigation completes, the reasoning LLM evaluates:
   - **Key findings**: What did we learn?
   - **Goal check**: `is_goal_reached` — Have we collected enough to fully answer the original question?
   - **Skip recommendations**: `skip_indices` — Which remaining investigations are now redundant?
   - **New investigations**: `new_investigations` — What new questions emerged from the results?
   - **Error handling**: If an investigation had timeouts or errors, suggests avoiding similar approaches in future investigations (e.g., "avoid large unindexed scans").

4. **`synthesize_deep_analysis`** — Final comprehensive synthesis.
   - Input: All accumulated findings, skipped/incomplete investigations, whether analysis was stopped early.
   - Output: Comprehensive markdown report with: direct answer, woven insights from all investigations, key discoveries, limitations, and suggestions for further analysis.
   - Uses reasoning LLM (senior data analyst persona).

**Adaptive behavior**:
- Investigations can be **skipped** if reasoning determines they're redundant.
- New investigations can be **added** based on discoveries.
- The loop terminates when: all investigations are done, goal is reached early, user requests stop, or max iterations exceeded.
- User can **stop** the meta-loop at any time; synthesis runs on whatever findings are available.

**Key differences from Extended**:
- Extended runs one plan with checkpoints. Deep Analysis runs multiple independent plans.
- Extended has a fixed number of steps (3–10). Deep Analysis has unlimited steps across investigations.
- Extended's checkpoints review the same plan. Deep Analysis's reasoning reviews across investigations and can modify the research agenda.
- Extended is auto-classified. Deep Analysis is user-opt-in.
- Deep Analysis produces a research-quality report with cross-investigation synthesis.

### 9.10 Shared Node Contracts

All subgraphs share node factories from `agent/nodes/common.py`. This table summarizes what each shared node does, which LLM it uses, and which modes use it.

| Node Factory | LLM Used | Modes | Responsibility |
|-------------|----------|-------|---------------|
| `make_planning_node` | Reasoning | Simple, Extended, Optimization | Generate execution plan (JSON with steps) |
| `make_execute_step_node` | None (direct execution) | Simple, Extended, Optimization | Execute current plan step (SQL/Python/Excel/etc.) |
| `make_debug_node` | Reasoning | Simple, Extended, Optimization | Fix failed code (up to max_retries) |
| `make_synthesize_node` | **Fast** | Simple | Generate final response from step results |
| `make_cost_check_node` | Reasoning + heuristic fallback | Simple, Extended, Optimization | 3-layer cost analysis |
| `make_strategy_gate_node` | Reasoning | Simple, Extended, Optimization | User-facing cost explanation + block |
| `make_validate_answer_node` | Reasoning | Quick only | Check if context-only answer is sufficient |
| `make_validate_result_node` | Reasoning | Simple, Optimization | Check if execution results answer the question |
| `make_replan_node` | Reasoning | Simple only | Create entirely new plan from scratch |
| (Extended-only) `checkpoint_node` | Reasoning | Extended only | Periodic progress review with continue/revise/done |
| (Extended-only) `revise_plan_node` | Reasoning | Extended only | Modify remaining steps (preserves completed work) |
| (Extended-only) `reflect_node` | Reasoning | Extended only | Holistic meta-analysis before synthesis |
| (Extended-only) `extended_synthesize_node` | **Reasoning** | Extended only | Comprehensive report using reflection |
| (Optimization-only) `optimize_plan_node` | Reasoning | Optimization only | Rewrite SQL with chosen strategy |
| (Optimization-only) `optimization_synthesize_node` | Reasoning | Optimization only | Synthesis with optimization metadata |

### 9.11 Mode Comparison Matrix

| Property | Quick | Simple | Optimization | Extended | Deep Analysis |
|----------|-------|--------|-------------|----------|--------------|
| **Code execution** | None | Yes | Yes | Yes | Yes (per investigation) |
| **Planning** | None | 1 plan, 1–5 steps | 1 plan + rewrite, 1–10 steps | 1 plan, 3–10 steps | 3–8 plans (1 per investigation) |
| **Cost gating** | No | Yes (blocks if expensive) | Yes (always blocks, user picks strategy) | Yes (blocks if expensive) | Per-investigation (inherits from subgraph) |
| **Self-correction** | Escalation only | Debug (3 retries) + 1 replan | Debug (3 retries) + plan rewrite | Debug (3 retries) + 2 revisions | Per-investigation + investigation adaptation |
| **Validation** | Is context sufficient? | Do results answer the question? | Always adequate (no replan) | Checkpoint: continue/revise/done | Reasoning: goal reached? skip? add? |
| **Reflection** | No | No | No | Yes (pre-synthesis) | Yes (cross-investigation synthesis) |
| **Synthesis LLM** | N/A (answer IS the response) | Fast LLM | Reasoning LLM | Reasoning LLM | Reasoning LLM |
| **User interaction mid-flow** | None | Strategy choice (if cost gate) | Strategy choice (always) | None (checkpoints are automatic) | Can stop early |
| **Max execution steps** | 0 | 5 + 5 (after replan) = 10 | 10 | 10 + 10 (after 2 revisions) = 30 | Unlimited |
| **Typical latency** | 1–3s | 5–30s | 10–60s (depending on strategy) | 15–120s | 60s–10min |

### 9.12 Classify Node — Source-Aware Extensions

The classifier is enhanced to understand source types:

```python
def make_classify_node(ctx: NodeContext):
    """Classify question and determine:
    1. Execution mode (quick/simple/extended/optimization_required)
    2. Target sources (which data sources are relevant)
    3. Whether cross-source operations are needed
    4. For Excel sources: whether this is a structure/formula question
       vs. a data extraction question
    """
```

Classification prompt additions for multi-source:
- List all active sources with their types and schemas
- For Excel: include sheet structure summaries (sheets, detected tables, formula count)
- For CSV: include table names and column info
- Flag if question references multiple sources

### 9.13 Execution Node — Source-Aware Actions

The `execute_step` node dispatches to source-specific tools based on `action` type:

| Action | Source | Implementation |
|--------|--------|---------------|
| `sql` | Database | `DatabaseSource.execute_query()` |
| `sql` | CSV | `CsvSource.execute_query()` (DuckDB) |
| `python` | Any | Sandboxed Python with `df`, `plt`, etc. |
| `excel_read` | Excel | `ExcelSource.read_range()` → CellGrid |
| `excel_structure` | Excel | `ExcelSource.get_sheet_structure()` |
| `excel_formula` | Excel | `FormulaAnalyzer.explain_formula()` |
| `excel_extract` | Excel | `ExcelSource.extract_table()` → DataFrame |
| `cross_query` | Multiple | `SessionManager.execute_cross_source_query()` |
| `schema` | Any | Get metadata/structure |
| `sample` | DB/CSV | Get sample rows |

### 9.14 Node Context

```python
# mcpdb/agent/nodes/__init__.py

@dataclass
class NodeContext:
    """Dependency injection container for all graph nodes."""
    llm: BaseChatModel               # Primary reasoning model
    fast_llm: BaseChatModel           # Fast model for synthesis
    session: SessionManager           # Multi-source session
    system_prompt: str                # Compiled system prompt with all source contexts
    callback_mgr: CallbackManager     # Streaming event emission
    experience_cache: ExactMatchCache  # Exact-match code cache (Section 11.5)
    experience_retriever: ExperienceRetriever  # Template matching & anti-patterns (Section 11.6)
    experience_recorder: ExperienceRecorder    # Auto-record outcomes (Section 11.9)
    cost_gate_enabled: bool
    cost_gate_auto_mode: bool
    max_retries: int
    sandbox: PythonSandbox            # Sandboxed Python executor
```

---

## 10. Streaming Event Protocol, Cancellation & User Interaction

### 10.1 Design Goals

Every step of the agent's thinking and execution MUST be streamed to the client in real-time so that:
1. The UI can display a **live, responsive progress view** (not just a spinner)
2. External MCP clients (Claude Desktop, IDE extensions, CLI) receive granular events they can present to users
3. Users can **cancel** at any point and receive partial results
4. Users can **inject additional context** mid-execution ("add more to thinking context")

### 10.2 Streaming Event Types

All events flow through the `CallbackManager` and are delivered to clients via **MCP-compliant mechanisms**:

**Transport strategy** (MCP protocol compliance):
- Events are surfaced via the **MCP `logging` capability** (`notifications/message` with level `info`/`debug`). The structured event payload is JSON-encoded in the message `data` field. This is the only MCP-standard way to stream arbitrary server → client messages.
- Additionally, events update **MCP resources** (`session://execution_status`), triggering `notifications/resources/updated` for subscribed clients.
- For the MCPDB-native frontend, a **direct WebSocket** transport bypasses MCP's notification model entirely for lower latency — the UI is not an MCP client, it is a custom client with its own streaming protocol.
- **Ordering**: Events are ordered per-session via monotonic sequence numbers. Clients that miss events can fetch the full event log via the `session://execution_status` resource.

Every event has a `timestamp`, `event_type`, and mode-specific payload.

```python
# mcpdb/agent/callbacks.py

class StreamingEvent(TypedDict):
    timestamp: float
    event_type: str       # See table below
    payload: dict         # Event-specific data


class CallbackManager:
    """Central hub for all streaming events.

    All agent nodes emit events through this manager.
    Events are:
      1. Buffered internally for state reconstruction
      2. Forwarded to registered listeners (MCP notification handlers, UI WebSocket)
      3. Logged for debugging

    Thread-safe. Supports multiple concurrent listeners.
    """

    def add_listener(self, listener: Callable[[StreamingEvent], None]) -> str: ...
    def remove_listener(self, listener_id: str) -> None: ...
    def emit(self, event_type: str, **payload) -> None: ...
```

**Complete event catalog** (ordered by typical occurrence within a single question):

| Event Type | Payload | Emitted By | When |
|-----------|---------|-----------|------|
| `classify/start` | `{question}` | Classify node | Question received, classification starting |
| `classify/result` | `{mode, reasoning, target_sources, mode_label}` | Classify node | Mode determined |
| `plan/start` | `{mode}` | Planning node | Plan generation starting |
| `plan/ready` | `{plan: {analysis, approach, steps}}` | Planning node | Plan generated (full plan JSON) |
| `cost_check/start` | `{}` | Cost check node | Cost analysis starting |
| `cost_check/result` | `{optimization_state, reason, estimated_rows?, estimated_time_ms?}` | Cost check node | Cost analysis complete |
| `strategy_request` | `{optimization_state, reason, cost_analysis, strategies: ["SAMPLE","FULL","CANCEL"]}` | Strategy gate node | User must choose strategy (blocks execution) |
| `step/start` | `{step_number, total_steps, action, description, source_id?}` | Execute node | Step execution starting |
| `step/code` | `{step_number, code_type, code}` | Execute node | Code about to run (for display) |
| `step/progress` | `{step_number, message}` | Execute node | Mid-step progress (e.g., "chunk 3/10 processed") |
| `step/success` | `{step_number, result_preview, time_ms, artifacts_produced}` | Execute node | Step completed successfully |
| `step/error` | `{step_number, error, attempt, max_attempts}` | Execute node | Step failed |
| `step/retry` | `{step_number, attempt, fix_description}` | Debug node | Retrying with corrected code |
| `artifact/created` | `{artifact_id, type, title, source_id?}` | Execute/Python | New artifact available (table, chart, cell_grid) |
| `validate/start` | `{type: "answer"\|"result"}` | Validator nodes | Validation starting |
| `validate/result` | `{result, reason?}` | Validator nodes | Validation complete |
| `replan/start` | `{reason}` | Replan node | Replanning starting |
| `replan/ready` | `{plan}` | Replan node | New plan generated |
| `checkpoint/start` | `{after_step, total_steps}` | Checkpoint node | Checkpoint review starting (Extended) |
| `checkpoint/result` | `{decision, reason}` | Checkpoint node | Checkpoint decision (continue/revise/done) |
| `revise/start` | `{reason}` | Revise plan node | Plan revision starting (Extended) |
| `revise/ready` | `{plan}` | Revise plan node | Revised plan ready (Extended) |
| `reflect/start` | `{}` | Reflect node | Reflection starting (Extended) |
| `reflect/ready` | `{reflection_preview}` | Reflect node | Reflection complete (Extended) |
| `synthesize/start` | `{mode}` | Synthesize nodes | Synthesis starting |
| `synthesize/complete` | `{response_preview}` | Synthesize nodes | Final response ready |
| `deep/blueprint` | `{goal, investigations: [{question, rationale}]}` | Deep Analysis | Blueprint created (Mode 5) |
| `deep/investigation_start` | `{index, question, total}` | Deep Analysis | Investigation starting (Mode 5) |
| `deep/investigation_complete` | `{index, question, summary, key_findings}` | Deep Analysis | Investigation done (Mode 5) |
| `deep/reasoning` | `{reasoning, is_goal_reached, skipped, new_investigations}` | Deep Analysis | Reasoning between investigations (Mode 5) |
| `deep/synthesis_start` | `{completed_count, total_count}` | Deep Analysis | Final synthesis starting (Mode 5) |
| `llm/start` | `{purpose, model, node}` | LLM wrapper | LLM call starting (e.g., purpose="planning", model="claude-sonnet-4-6") |
| `llm/token` | `{delta, accumulated_length}` | LLM wrapper | Token chunk received during streaming LLM call |
| `llm/complete` | `{purpose, tokens_in, tokens_out, time_ms, cost_usd}` | LLM wrapper | LLM call completed with usage stats |
| `thinking` | `{message, level: "info"\|"planning"\|"executing"\|"debugging"\|"error"}` | Any node | General thinking/status update |
| `error` | `{message, recoverable}` | Any node | Error occurred |
| `complete` | `{success, message}` | Final node | Execution complete |
| `cancelled` | `{reason, partial_results_available}` | Cancellation handler | Execution was cancelled |

### 10.2.1 LLM Token-Level Streaming (Thinking Visibility)

High-level events (`plan/start`, `step/success`) give structure, but users need to see **what the LLM is thinking in real time** — not just "planning..." then silence for 15 seconds.

**All LLM calls MUST use streaming mode** (provider SDKs support this: Anthropic `stream=True`, OpenAI `stream=True`, Google `stream=True`). The `LLMClient` wrapper in Section 13 emits `llm/token` events as chunks arrive:

```python
# mcpdb/llm/client.py (streaming wrapper)

async def stream_llm_call(
    self,
    messages: list[dict],
    purpose: str,          # "classify", "plan", "debug", "synthesize", "cost_check", etc.
    cancel_token: CancellationToken,
    callback_manager: CallbackManager,
) -> str:
    """Stream an LLM call, emitting token events and checking cancellation per chunk."""

    callback_manager.emit("llm/start", purpose=purpose, model=self.model_id, node=purpose)

    accumulated = []
    async for chunk in self.provider.stream(messages):
        cancel_token.check()  # Check cancellation between chunks
        accumulated.append(chunk.text)
        callback_manager.emit("llm/token", delta=chunk.text, accumulated_length=len(accumulated))

    full_text = "".join(accumulated)
    callback_manager.emit("llm/complete",
        purpose=purpose,
        tokens_in=chunk.usage.input_tokens,
        tokens_out=chunk.usage.output_tokens,
        time_ms=elapsed,
        cost_usd=estimated_cost,
    )
    return full_text
```

**What the user sees in real time** (by purpose):

| LLM Purpose | What Streams | User Experience |
|-------------|-------------|-----------------|
| `classify` | Mode reasoning | User sees "This looks like a simple aggregation on a small table..." as it's generated |
| `plan` | Step-by-step plan JSON | User sees plan steps appearing one by one as the LLM generates them |
| `cost_check` | Cost analysis reasoning | User sees "The query involves a full scan on orders (2.5M rows)..." |
| `debug` | Error analysis + fix | User sees "The error is due to ambiguous column 'name'... fixing by qualifying as customers.name" |
| `synthesize` | Final response markdown | User sees the final answer being written word by word |
| `checkpoint` | Checkpoint reasoning | User sees "Steps 1-3 completed. Revenue data looks correct. Step 4 needs revision because..." |
| `deep/reasoning` | Meta-reasoning | User sees "Investigation 2 revealed that churn is seasonal. Next I should examine Q4 specifically..." |

**Throttling for MCP transport**: `llm/token` events are high-frequency (10-50/sec). For non-WebSocket transports:
- **stdio**: Batch tokens into 200ms windows, emit one `llm/token` per window with accumulated delta
- **SSE**: Same 200ms batching
- **WebSocket (native UI)**: No batching, emit every token immediately for typewriter effect

**Client rendering**:
- Rich UI: Typewriter effect in a "Thinking" panel, with purpose label (e.g., "Planning...", "Analyzing error...")
- CLI: Print tokens to stderr as they arrive, with dimmed color to distinguish from final output
- MCP clients (Claude Desktop): Tokens flow through `notifications/message` — the client decides rendering

### 10.3 Cancellation Support

Users MUST be able to cancel any in-progress operation at any point — including **killing in-flight SQL queries and LLM calls**. Cancellation is graceful — partial results are preserved and returned.

#### 10.3.1 Cancellation Token (orchestrator-level)

```python
# mcpdb/agent/cancellation.py

class CancellationToken:
    """Thread-safe cancellation signal checked at natural pause points.

    Usage:
      - Client calls cancel_execution(reason) via MCP tool
      - CancellationToken.is_cancelled becomes True
      - Each node checks the token at natural pause points:
        - Before executing each plan step
        - Before each LLM call
        - Before each SQL query
        - At each checkpoint (Extended)
        - Between investigations (Deep Analysis)
      - When cancelled, nodes perform cleanup and return partial results
    """

    def __init__(self):
        self._cancelled = threading.Event()
        self._reason: str = ""

    def cancel(self, reason: str = "User cancelled") -> None: ...
    @property
    def is_cancelled(self) -> bool: ...
    @property
    def reason(self) -> str: ...
    def check(self) -> None:
        """Raise CancelledException if cancelled. Call at every natural pause point."""
        ...


class CancelledException(Exception):
    """Raised when execution is cancelled. Caught by the orchestrator."""
    def __init__(self, reason: str, partial_state: AgentState): ...
```

#### 10.3.2 In-Flight SQL Query Cancellation (database-level)

The orchestrator-level token only works **between** steps. Once a SQL query is dispatched to `execute_query()` in the thread pool, the token can't stop it. To kill running queries, the system uses **database-level cancellation**:

```python
# mcpdb/sources/database/query_runner.py

class CancellableQueryRunner:
    """Wraps execute_query with database-level cancellation support.

    Architecture:
      1. Before executing SQL, records the DBAPI connection and backend PID
      2. Dispatches query to thread pool via run_in_executor()
      3. Monitors CancellationToken in a separate coroutine (asyncio)
      4. If token fires, calls dialect.cancel_query() on a SEPARATE connection
         to kill the running query on the server side
      5. The thread pool worker receives a database error and raises CancelledException
    """

    async def execute_cancellable(
        self,
        source: DatabaseSource,
        sql: str,
        cancel_token: CancellationToken,
        max_rows: int = 100,
    ) -> pd.DataFrame:
        # Get connection PID/ID BEFORE executing
        conn_info = source.get_active_connection_info()

        # Run query in thread pool
        query_future = asyncio.get_event_loop().run_in_executor(
            thread_pool, source.execute_query, sql, None, max_rows
        )

        # Monitor cancellation in parallel
        cancel_future = asyncio.get_event_loop().run_in_executor(
            thread_pool, cancel_token._cancelled.wait, None  # blocks until cancel or query done
        )

        done, pending = await asyncio.wait(
            [query_future, cancel_future],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if cancel_future in done and query_future not in done:
            # Cancellation requested — kill the query at the database level
            source.dialect.cancel_query(conn_info)
            query_future.cancel()
            raise CancelledException(cancel_token.reason, ...)

        return query_future.result()
```

**Dialect-specific kill commands** (new method on `DatabaseDialect`):

| Dialect | `cancel_query(conn_info)` Implementation |
|---------|------------------------------------------|
| PostgreSQL | `SELECT pg_cancel_backend(:pid)` — sends SIGINT to backend. If still running after 2s: `SELECT pg_terminate_backend(:pid)` |
| MySQL | `KILL QUERY :thread_id` — kills only the query, keeps connection. Uses `CONNECTION_ID()` captured before execution |
| SQL Server | `KILL :session_id` — terminates session. Session ID from `@@SPID` captured before execution |
| Oracle | `ALTER SYSTEM KILL SESSION ':sid,:serial#' IMMEDIATE` — kills session. SID/Serial from `V$SESSION` |
| SQLite | N/A (in-process, uses `sqlite3.interrupt()` on the connection object) |
| DuckDB (CSV) | `duckdb.interrupt()` on the connection object |

**Connection info tracking**: Before each SQL execution, the connector captures the backend process/session ID:
```python
# In DatabaseSource.execute_query():
with self.engine.connect() as conn:
    # Capture PID for cancellation
    pid_query = self.dialect.get_backend_pid_query()  # e.g., "SELECT pg_backend_pid()"
    self._active_pid = conn.execute(text(pid_query)).scalar()
    # Execute the actual query
    result = conn.execute(text(query), params or {})
```

New dialect methods:
- `get_backend_pid_query() -> str` — Returns SQL to fetch current connection's backend PID/session ID
- `cancel_query(conn_info: dict) -> None` — Issues kill command on a **separate** connection (cannot use the connection that's busy executing)

#### 10.3.3 LLM Call Cancellation

LLM API calls (planning, debugging, synthesis) can take 10-30s. These are also cancellable:

- **HTTP-level**: LLM provider SDKs support request cancellation. When `CancellationToken` fires, the system calls `.cancel()` or `.close()` on the HTTP client/stream.
- **Streaming LLM calls** (see Section 10.8): Since LLM responses are streamed token-by-token, the system checks `CancellationToken.is_cancelled` after each chunk. If cancelled, the partial LLM output collected so far is used (e.g., a partially generated plan is discarded, but a partially generated synthesis response may be usable).

#### 10.3.4 Python Sandbox Cancellation

When the user cancels during Python sandbox execution:
- The sandbox runs as a **subprocess** (see Section 14)
- Cancellation sends `SIGTERM` to the subprocess, with `SIGKILL` after 2s grace period
- Partial output (stdout/stderr captured so far) is preserved

#### 10.3.5 Cancellation Behavior Per Mode

| Mode | Cancellation point | What happens |
|------|-------------------|-------------|
| Quick | Before/during LLM call | HTTP request cancelled, returns empty response |
| Simple | Before/during each step | In-flight SQL killed, synthesizes partial results from completed steps |
| Optimization | Before/during each step, during strategy gate | If waiting for strategy: cancels entirely. During execution: in-flight query killed, partial synthesis |
| Extended | Before/during each step, at checkpoint | In-flight query killed, skips to reflect → synthesize with whatever is done |
| Deep Analysis | Between/during investigations | In-flight query killed, synthesizes from completed investigations |

**Post-cancellation cleanup**:
- Database connection is returned to pool (if not terminated) or discarded (if terminated)
- Temporary DuckDB tables created during cross-source federation are dropped
- Sandbox subprocess is killed if still running
- All artifacts created before cancellation are preserved and returned

#### 10.3.6 MCP Tool for Cancellation

```json
{
    "name": "cancel_execution",
    "description": "Cancel the currently running analysis. In-flight SQL queries will be killed at the database level. Partial results will be returned.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Why the user is cancelling (optional)"}
        }
    }
}
```

### 10.4 "Add More Context" — Mid-Execution User Input

Users can inject additional context or instructions while the agent is executing. This is critical for interactive analysis sessions where the user notices something mid-execution and wants to steer the analysis.

**Two interaction patterns**:

#### 10.4.1 Pre-Step Injection (Synchronous)

Before executing the next step, the agent checks for pending user messages. If found, the message is appended to the conversation context and the current plan is re-evaluated.

```python
# mcpdb/agent/user_input_queue.py

class UserInputQueue:
    """Thread-safe queue for mid-execution user input.

    When a user sends a message while execution is in progress:
      1. The message is enqueued (not dropped)
      2. The execute node checks the queue before each step
      3. If a message is found:
         a. It's appended to state.messages
         b. A flag is set indicating mid-execution input
         c. The current plan may be revised to incorporate the new context
    """

    def enqueue(self, message: str) -> None: ...
    def dequeue(self) -> str | None: ...
    @property
    def has_pending(self) -> bool: ...
```

**Behavior**: When mid-execution input is detected:
- In **Simple** mode: Triggers an immediate replan (counts toward the 1-replan limit). The new plan incorporates both the original question and the additional context.
- In **Extended** mode: Treated as an immediate checkpoint trigger. The checkpoint node sees the new context and can revise remaining steps.
- In **Deep Analysis** mode: Injected into the reasoning phase. The LLM sees the user's additional input when deciding next investigations.

#### 10.4.2 Strategy Response (Asynchronous)

For cost gate interactions, the user's strategy choice arrives as a new tool call. The `session_id` ties it back to the saved `AgentState` (see Strategy Gate State Machine in Section 9.6):
```json
{
    "name": "submit_strategy",
    "description": "Choose optimization strategy for a cost-gated query. Must be called within 10 minutes of the strategy_request event.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Session ID from the ask_question response that triggered the cost gate"},
            "strategy": {"type": "string", "enum": ["SAMPLE", "FULL", "CANCEL"]},
            "custom_instructions": {"type": "string", "description": "Optional: additional instructions for the optimizer"}
        },
        "required": ["session_id", "strategy"]
    }
}
```

**Error cases**:
- `session_id` not found in `pending_strategies` → error: "No pending strategy request for this session"
- Strategy expired (>10 min) → error: "Strategy request expired. Please re-ask the question."
- `CANCEL` strategy → clears pending state, returns `{status: "cancelled"}`

### 10.5 Full Pipeline Observability for MCP Clients

**Design requirement**: Any MCP client — Claude Desktop, a CLI tool, a custom IDE extension — MUST be able to track the **entire thinking process** from question to answer. This is not optional UI chrome; it's a core MCP protocol capability.

#### 10.5.1 Thinking Pipeline Phases (what MCP clients observe)

Every `ask_question` call produces a **deterministic sequence of observable phases**. The MCP client sees each phase start, its real-time reasoning, and its conclusion:

```
Phase 1: CLASSIFY
  ├── llm/start {purpose: "classify"}
  ├── llm/token × N  (client sees: "This is a revenue aggregation on a medium table...")
  ├── llm/complete {tokens_in: 800, tokens_out: 150, cost: $0.002}
  └── classify/result {mode: "simple", reasoning: "...", target_sources: ["postgres_main"]}

Phase 2: PLAN
  ├── plan/start {mode: "simple"}
  ├── llm/start {purpose: "plan"}
  ├── llm/token × N  (client sees plan JSON being generated step by step)
  ├── llm/complete {tokens_in: 2000, tokens_out: 500, cost: $0.008}
  └── plan/ready {plan: {steps: [...]}}

Phase 3: COST CHECK
  ├── cost_check/start
  ├── [EXPLAIN queries run — no LLM needed if low-cost]
  ├── [OR: llm/start → llm/token × N → llm/complete if EXPLAIN flags concerns]
  └── cost_check/result {optimization_state: "not_required", estimated_rows: 50000}

Phase 4: EXECUTE (per step)
  ├── step/start {step_number: 1, total_steps: 2, action: "sql"}
  ├── step/code {code: "SELECT ..."}
  ├── step/progress {message: "Query executing..."} (for long queries)
  ├── step/success {result_preview: "10 rows", time_ms: 340}
  └── artifact/created {type: "dataframe", title: "Top customers"}

Phase 5: VALIDATE
  ├── validate/start
  ├── llm/start {purpose: "validate"}
  ├── llm/token × N  (client sees: "The results show top 10 customers by revenue, which answers...")
  ├── llm/complete
  └── validate/result {result: "adequate"}

Phase 6: SYNTHESIZE
  ├── synthesize/start
  ├── llm/start {purpose: "synthesize"}
  ├── llm/token × N  (client sees final response being written word by word)
  ├── llm/complete
  └── synthesize/complete {response_preview: "The top customer is..."}

DONE: complete {success: true, message: "Analysis complete"}
```

**Key guarantee**: Between `llm/start` and `llm/complete`, the client receives `llm/token` events in real time. The client is **never waiting in the dark** — there is always either a token streaming or a status event explaining what's happening.

#### 10.5.2 MCP Transport Mechanisms

Events are delivered differently based on transport:

| Transport | Mechanism | Client | Latency |
|-----------|-----------|--------|---------|
| **stdio** | JSON-RPC notifications on stdout | Claude Desktop, CLI | ~0ms |
| **SSE** | Server-Sent Events stream | Web clients | ~10ms |
| **WebSocket** | JSON messages on WS connection | MCPDB Frontend, custom UIs | ~5ms |

**MCP `logging` capability** (primary mechanism for all MCP clients):
```json
{
  "jsonrpc": "2.0",
  "method": "notifications/message",
  "params": {
    "level": "info",
    "logger": "mcpdb.agent",
    "data": {
      "seq": 42,
      "event_type": "llm/token",
      "payload": {"delta": "considering the orders table", "accumulated_length": 230}
    }
  }
}
```

**MCP resource subscriptions** (for state polling clients):
- `session://execution_status` — Updated on every phase transition. Clients that can't process real-time notifications can poll this resource.
- `session://thinking_log` — Append-only log of all events. Clients can fetch the full log at any time to reconstruct the thinking pipeline.

**Event delivery contract**:
- Events are delivered in order, never dropped
- Each event is self-contained (no need to reconstruct from deltas)
- Events include enough context for a client to render a meaningful UI without maintaining internal agent state
- The `step/start` event includes `total_steps` so clients can show progress bars
- The `artifact/created` event includes the artifact ID; clients fetch the full artifact via `get_artifact` tool
- `llm/token` events are batched for non-WebSocket transports (200ms windows) to avoid flooding

#### 10.5.3 Non-Blocking Guarantees

The architecture ensures the MCP client is **never blocked** and can always interact:

1. **`ask_question` returns immediately** — The tool response includes only a `session_id`. All subsequent events stream via notifications. The client is free to call other tools (`cancel_execution`, `add_context`, `get_session_status`) while the agent works.

2. **Concurrent tool calls** — MCP supports multiple in-flight requests. While `ask_question` is processing in the background, the client can:
   - Call `cancel_execution` to stop the analysis
   - Call `add_context` to inject new information (queued via `UserInputQueue`)
   - Call `get_session_status` to poll current state
   - Call any read-only tool (`get_source_schema`, `list_sources`, etc.)

3. **Strategy gate is non-blocking** — When the cost gate fires, the graph emits `strategy_request` event and **returns the `ask_question` tool response** with `status: "awaiting_strategy"`. The client is NOT blocked — it processes the event, shows strategy buttons to the user, and eventually calls `submit_strategy` as a **separate tool call**.

4. **Database queries don't block the event loop** — SQL execution runs in `ThreadPoolExecutor`, so the asyncio event loop continues processing MCP requests (including `cancel_execution`) while queries run.

5. **LLM calls don't block the event loop** — LLM streaming calls are `async` (provider SDKs support async streaming). The event loop processes MCP requests between token chunks.

### 10.6 Client-Side Event Handling Examples

**Minimal CLI client** (shows full thinking in real-time):
```
🧠 Classifying... This is a revenue aggregation on a medium-sized table
⚡ Mode: Simple Analysis (2-step plan)
📋 Planning... Step 1: Query top customers by revenue from orders table
              Step 2: Create visualization with matplotlib
📊 Checking cost... EXPLAIN estimates 50K rows, no optimization needed
▶ Step 1/2: [sql] SELECT customer_name, SUM(amount)...
  ✅ 10 rows (0.3s)
▶ Step 2/2: [python] Creating bar chart...
  ✅ 1 chart (0.8s)
✓ Validating... Results correctly show top customers by revenue ✓
📝 Writing response... The top customer by revenue is Acme Corp with $1.2M...
✅ Done (3.4s total, $0.015 LLM cost)
```

**Rich UI client** (renders all event types):
- Collapsible "Thinking" panel with typewriter effect for LLM reasoning
- Phase progress indicator (Classify → Plan → Cost Check → Execute → Validate → Synthesize)
- Step-by-step execution monitor with timing and status icons
- Artifact gallery (tables, charts) that updates as artifacts are created
- Cancel button that calls `cancel_execution` tool
- "Add context" input field that enqueues via `UserInputQueue` during execution
- LLM cost running total in status bar
- Deep Analysis: investigation progress tracker with expandable findings and reasoning

### 10.7 Package Structure for Streaming & Interaction

```
mcpdb/agent/
├── callbacks.py              # CallbackManager, StreamingEvent, event emission
├── cancellation.py           # CancellationToken, CancelledException
└── user_input_queue.py       # UserInputQueue for mid-execution context injection

mcpdb/mcp/
├── notifications.py          # MCP notification handlers (emit events to transport)
└── ...
```

---

## 11. Per-Source Experience & Learning System

### 11.1 Design Goals

The system MUST learn from every interaction and improve over time. Each data source (database, CSV set, Excel workbook) maintains an **independent experience store** so that:

1. **Exact-match code caching** — when a user asks a question that has been successfully answered before (identical intent + identical schema), the cached code is returned **without invoking the LLM**, achieving zero-latency replay
2. **Template reuse** — when a question is *similar* to a previously successful one (same tables/columns, different filters or aggregations), the cached code is used as a **starting template** so the LLM produces higher-quality code with fewer mistakes
3. **Error avoidance** — failed queries and their fixes are recorded so the planning and debug nodes avoid known pitfalls
4. **Strategy memory** — successful optimization strategies (SAMPLE vs FULL, specific SQL rewrites) are recalled for similar cost-gated scenarios
5. **Per-source isolation** — a PostgreSQL analytics database's experience never pollutes a separate MySQL operations database's patterns; CSV/Excel sources have their own stores
6. **Cross-dialect transfer** — dialect-level patterns (e.g., "Oracle requires explicit GROUP BY for all non-aggregate columns") are shared across all sources of the same database type

### 11.2 Source Fingerprinting

Each source is identified by a **stable fingerprint** so experience persists across sessions even if display names change.

```python
# mcpdb/experience/fingerprint.py

@dataclass(frozen=True)
class SourceFingerprint:
    """Unique identifier for an experience store."""
    source_type: Literal["database", "csv", "excel"]
    identity_hash: str   # Stable hash — see below

    @staticmethod
    def for_database(connection_string: str) -> "SourceFingerprint":
        """Hash host + port + database name (NOT credentials)."""
        parsed = make_url(connection_string)
        identity = f"{parsed.drivername}://{parsed.host}:{parsed.port}/{parsed.database}"
        return SourceFingerprint("database", hashlib.sha256(identity.encode()).hexdigest()[:16])

    @staticmethod
    def for_csv(file_paths: list[str], column_signatures: dict[str, list[str]]) -> "SourceFingerprint":
        """Hash sorted file basenames + column names (NOT full paths)."""
        sig = json.dumps({
            "files": sorted(Path(p).name for p in file_paths),
            "columns": {k: sorted(v) for k, v in sorted(column_signatures.items())}
        }, sort_keys=True)
        return SourceFingerprint("csv", hashlib.sha256(sig.encode()).hexdigest()[:16])

    @staticmethod
    def for_excel(file_path: str, sheet_names: list[str]) -> "SourceFingerprint":
        """Hash filename + sheet names."""
        sig = json.dumps({"file": Path(file_path).name, "sheets": sorted(sheet_names)}, sort_keys=True)
        return SourceFingerprint("excel", hashlib.sha256(sig.encode()).hexdigest()[:16])

    @property
    def store_dir_name(self) -> str:
        return f"{self.source_type}_{self.identity_hash}"
```

### 11.3 Experience Record Types

All records are immutable once created. User votes can update the `feedback_score` field.

```python
# mcpdb/experience/records.py

@dataclass
class SuccessRecord:
    """A successfully executed and validated code block."""
    id: str                           # UUID
    timestamp: float
    source_fingerprint: str
    question: str                     # Original user question (normalized)
    question_embedding: list[float]   # Embedding vector for semantic search
    intent_hash: str                  # Hash of normalized question for exact-match
    mode: str                         # quick/simple/extended/optimization/deep_analysis
    plan_json: dict | None            # The plan that was executed (for multi-step)

    # --- Code payload ---
    steps: list[CodeStep]             # Ordered list of executed code blocks
    synthesis: str                    # Final answer text
    artifacts: list[str]              # Artifact IDs (charts, tables)

    # --- Schema context at time of execution ---
    schema_hash: str                  # Hash of relevant table/column names used
    tables_used: list[str]            # Tables/sheets referenced
    columns_used: list[str]           # Columns referenced

    # --- Quality signals ---
    feedback_score: int               # +1 upvote, -1 downvote, 0 no feedback
    execution_time_ms: int            # Total execution time
    error_count: int                  # Errors encountered before success (0 = clean run)
    reuse_count: int                  # How many times this record was reused as cache/template

@dataclass
class CodeStep:
    """A single executable step within a SuccessRecord."""
    step_number: int
    action: str                       # sql, python, excel_read, etc.
    source_id: str | None
    code: str                         # The actual SQL/Python code
    code_hash: str                    # SHA-256 of normalized code (whitespace-insensitive)


@dataclass
class FailureRecord:
    """A failed execution — stored to avoid repeating the same mistake."""
    id: str
    timestamp: float
    source_fingerprint: str
    question: str
    question_embedding: list[float]
    mode: str

    # --- What went wrong ---
    failed_code: str                  # The code that failed
    error_message: str                # Error string
    error_category: str               # syntax, runtime, timeout, wrong_result, etc.
    root_cause: str                   # LLM-generated root cause explanation

    # --- What fixed it (if anything) ---
    fix_code: str | None              # The corrected code (None if never fixed)
    fix_explanation: str | None       # LLM-generated fix explanation
    tables_involved: list[str]


@dataclass
class StrategyRecord:
    """A cost-gating strategy decision and its outcome."""
    id: str
    timestamp: float
    source_fingerprint: str
    question: str
    question_embedding: list[float]
    tables_involved: list[str]
    estimated_rows: int
    strategy_chosen: str              # SAMPLE, FULL, CANCEL
    sql_rewrite: str | None           # Optimized SQL (if SAMPLE)
    outcome: str                      # success, timeout, wrong_result
    execution_time_ms: int
    feedback_score: int
```

### 11.4 Storage Layout

```
~/.mcpdb/experience/
├── index.json                        # Maps fingerprint → metadata (last used, record counts)
│
├── database_a1b2c3d4/               # One directory per source fingerprint
│   ├── metadata.json                 # Source info: type, dialect, schema snapshot
│   ├── success_records.jsonl         # Append-only JSONL
│   ├── failure_records.jsonl
│   ├── strategy_records.jsonl
│   ├── embeddings.npz                # Numpy compressed: all vectors in one file
│   ├── intent_cache.json             # intent_hash → record_id (exact-match lookup)
│   └── schema_hashes.json            # schema_hash → timestamp (detect schema drift)
│
├── csv_e5f6g7h8/
│   ├── metadata.json
│   ├── success_records.jsonl
│   ├── ...
│
├── excel_i9j0k1l2/
│   ├── ...
│
└── dialect_patterns/                 # Cross-source, per-dialect knowledge
    ├── postgresql.jsonl              # Dialect-specific patterns and anti-patterns
    ├── mysql.jsonl
    ├── sqlite.jsonl
    ├── mssql.jsonl
    ├── oracle.jsonl
    └── duckdb.jsonl                  # For CSV sources
```

**Storage limits** (per source):
- Max 2000 success records (LRU eviction based on `reuse_count` and `feedback_score`)
- Max 500 failure records (oldest evicted first)
- Max 200 strategy records
- Embeddings file rebuilt on eviction

### 11.5 Exact-Match Code Cache (Skip LLM)

The fastest path: if the user asks the **same question** about the **same schema**, return the cached answer immediately.

```python
# mcpdb/experience/cache.py

class ExactMatchCache:
    """O(1) lookup for previously answered questions.

    Cache hit criteria (ALL must match):
      1. intent_hash matches (normalized question → SHA-256)
      2. schema_hash matches (tables + columns still exist in source)
      3. feedback_score >= 0 (not downvoted)
      4. Record age < max_cache_age (default 30 days)

    On cache hit:
      - Return the stored synthesis + artifacts directly
      - Emit StreamingEvent(type="cache_hit", record_id=...)
      - Increment reuse_count on the record
      - Do NOT invoke any LLM call
    """

    def normalize_question(self, question: str) -> str:
        """Normalize for intent hashing.

        Steps:
          1. Lowercase
          2. Strip punctuation except operators (>, <, =, %)
          3. Collapse whitespace
          4. Remove stop words (the, a, an, is, are, show, me, please, can, you)
          5. Stem remaining words (Porter stemmer: "customers" → "custom",
             "showing" → "show") to match inflection variants

        NOTE: Words are NOT sorted. Word order carries semantic meaning
        ("revenue by customer" ≠ "customer by revenue"). The normalization
        preserves order while reducing surface variation.

        The intent_hash is SHA-256 of the normalized string. This means
        only near-identical phrasings will match. For semantic similarity
        (paraphrases, synonyms), the template matching path (Section 11.6)
        handles it via embeddings.
        """

    def compute_schema_hash(self, tables_used: list[str], source: DataSource) -> str:
        """Hash the current schema for the tables referenced by the record.

        If a table was dropped or columns were renamed, the hash won't match
        and the cache entry is invalidated (stale schema).
        """

    def lookup(self, question: str, source: DataSource) -> SuccessRecord | None:
        """Return cached record or None."""
```

**Integration point**: The `classify` node checks the cache BEFORE invoking the classification LLM. If a cache hit occurs, the entire agent graph is bypassed.

### 11.6 Template Matching (Near-Miss Reuse)

When there is no exact cache hit, the system searches for **semantically similar** successful queries to use as templates.

```python
# mcpdb/experience/retriever.py

class ExperienceRetriever:
    """Semantic search over experience records for a given source.

    Retrieval pipeline:
      1. Embed the user question
      2. Cosine similarity search against success_records embeddings
      3. Apply boosting:
         - +0.15 if same tables are referenced (table overlap ratio)
         - +0.10 if same mode classification
         - +0.05 per positive feedback_score (capped at +0.15)
         - −0.20 if schema_hash is stale (tables/columns changed)
      4. Apply filtering:
         - Exclude records with feedback_score < 0 (downvoted)
         - Exclude records older than max_age (default 90 days for templates)
      5. Return top-K results (K=3 for planning, K=5 for debugging)

    Similarity thresholds:
      - >= 0.85: HIGH confidence — inject as "Use this code as a starting template"
      - >= 0.65: MEDIUM confidence — inject as "Reference these similar examples"
      - < 0.65: No match — normal planning without templates

    Template injection format (into planning prompt):
      SIMILAR SUCCESSFUL QUERIES (adapt to current question):
      ---
      Question: "{similar_question}"
      Code:
      ```sql
      {code}
      ```
      Result summary: {synthesis_excerpt}
      ---
    """

    def retrieve_for_planning(
        self,
        question: str,
        source_fingerprint: str,
        tables_in_scope: list[str],
        mode: str,
        top_k: int = 3,
    ) -> list[tuple[SuccessRecord, float]]:
        """Return (record, score) pairs for planning context."""

    def retrieve_for_debugging(
        self,
        error_message: str,
        failed_code: str,
        source_fingerprint: str,
        top_k: int = 5,
    ) -> list[FailureRecord]:
        """Return failure records with known fixes for similar errors."""

    def retrieve_strategies(
        self,
        question: str,
        source_fingerprint: str,
        tables_involved: list[str],
        top_k: int = 3,
    ) -> list[StrategyRecord]:
        """Return strategy records for cost-gating decisions."""
```

### 11.7 Anti-Pattern Tracking

Failed executions are tracked to **prevent repeating known mistakes**.

```python
# Integration with planning node:

# During plan generation, the planner receives:
KNOWN ISSUES FOR THIS SOURCE:
---
- When querying table "orders": Do NOT use `DATE(created_at)` — this column is
  already DATE type, casting causes index bypass. Use direct comparison instead.
  (Error seen 3 times, last: 2024-12-15)
- Table "products" column "price" is VARCHAR not NUMERIC. Always CAST(price AS DECIMAL)
  before arithmetic. (Error seen 5 times)
---

# Anti-pattern injection criteria:
#   - FailureRecord.tables_involved overlaps with plan's target tables
#   - FailureRecord has occurred >= 2 times (not a one-off)
#   - FailureRecord is less than 90 days old
#   - Max 5 anti-patterns per planning prompt (to avoid overwhelming context)
```

### 11.8 Cross-Dialect Knowledge Transfer

Some patterns are **not source-specific but dialect-specific** — they apply to all PostgreSQL databases, for example.

```
Dialect-level patterns (stored in ~/.mcpdb/experience/dialect_patterns/):

- Captured when: A FailureRecord's root_cause or SuccessRecord's code reveals
  a dialect-specific pattern (e.g., "Oracle requires explicit GROUP BY",
  "MySQL string comparison is case-insensitive by default")

- Promoted when: The same pattern appears in >= 2 different sources of the same
  dialect type

- Injected into: The SQL syntax rules section of planning/debug prompts, alongside
  the static dialect rules from DatabaseDialect.get_sql_syntax_rules()

- Format:
  @dataclass
  class DialectPattern:
      dialect: str                    # postgresql, mysql, etc.
      pattern_type: str               # anti_pattern, best_practice, gotcha
      description: str                # Human-readable explanation
      example_bad: str | None         # Code that triggers the issue
      example_good: str | None        # Correct code
      occurrence_count: int           # How many times seen across sources
      source_fingerprints: list[str]  # Which sources contributed this pattern
```

### 11.9 Recording Pipeline

Experience is recorded **automatically** at key points in the agent execution:

```
Recording triggers:
┌──────────────────────────────┬────────────────────────────────────────┐
│ Trigger Point                │ What Is Recorded                       │
├──────────────────────────────┼────────────────────────────────────────┤
│ Synthesis node completes     │ SuccessRecord (all steps + synthesis)  │
│ successfully                 │                                        │
├──────────────────────────────┼────────────────────────────────────────┤
│ Debug node fixes an error    │ FailureRecord (with fix_code)          │
├──────────────────────────────┼────────────────────────────────────────┤
│ Max debug retries exhausted  │ FailureRecord (fix_code = None)        │
├──────────────────────────────┼────────────────────────────────────────┤
│ Strategy gate completes      │ StrategyRecord (strategy + outcome)    │
│ execution                    │                                        │
├──────────────────────────────┼────────────────────────────────────────┤
│ User upvotes/downvotes       │ Update feedback_score on existing      │
│ a response                   │ record                                 │
├──────────────────────────────┼────────────────────────────────────────┤
│ Cache hit serves a response  │ Increment reuse_count                  │
├──────────────────────────────┼────────────────────────────────────────┤
│ Schema drift detected        │ Mark stale records via schema_hash     │
│ (column/table removed)       │ mismatch                               │
└──────────────────────────────┴────────────────────────────────────────┘
```

### 11.10 Integration with Agent Nodes

The experience system integrates at these specific points in the agent graph:

```
┌─────────────────────────────────────────────────────────────────┐
│                   Agent Graph Integration                        │
│                                                                  │
│  ┌──────────┐                                                   │
│  │ CLASSIFY │──→ ExactMatchCache.lookup()                       │
│  │          │    ↓ HIT: bypass entire graph, return cached      │
│  │          │    ↓ MISS: continue to classification LLM         │
│  └──────────┘                                                   │
│       ↓                                                          │
│  ┌──────────┐                                                   │
│  │  PLAN    │──→ ExperienceRetriever.retrieve_for_planning()    │
│  │          │    Inject: templates (HIGH), examples (MED),      │
│  │          │    anti-patterns from FailureRecords              │
│  └──────────┘                                                   │
│       ↓                                                          │
│  ┌──────────┐                                                   │
│  │COST CHECK│──→ ExperienceRetriever.retrieve_strategies()      │
│  │          │    Inject: "Last time, SAMPLE strategy worked     │
│  │          │    for similar query on this table"               │
│  └──────────┘                                                   │
│       ↓                                                          │
│  ┌──────────┐                                                   │
│  │ EXECUTE  │──→ (no injection — executes as planned)           │
│  └──────────┘                                                   │
│       ↓                                                          │
│  ┌──────────┐                                                   │
│  │  DEBUG   │──→ ExperienceRetriever.retrieve_for_debugging()   │
│  │          │    Inject: "This error was fixed before by..."    │
│  └──────────┘                                                   │
│       ↓                                                          │
│  ┌──────────┐                                                   │
│  │SYNTHESIZE│──→ ExperienceRecorder.record_success()            │
│  │          │    + update intent_cache for future exact-match   │
│  └──────────┘                                                   │
│       ↓                                                          │
│  ┌──────────┐                                                   │
│  │  USER    │──→ Vote ±1 → ExperienceRecorder.record_feedback() │
│  │ FEEDBACK │                                                    │
│  └──────────┘                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 11.11 Embedding Strategy

```python
# mcpdb/experience/embeddings.py

class EmbeddingService:
    """Manages embedding generation and vector search.

    Provider hierarchy (same as main LLM, configured independently):
      1. Anthropic: voyage-3-lite (1024 dims)
      2. Google: text-embedding-004 (768 dims)
      3. OpenAI: text-embedding-3-small (1536 dims)
      4. Fallback: Jaccard word-overlap similarity (no embeddings needed)

    Embedding is computed for:
      - question field of all record types
      - error_message field of FailureRecords (separate vector space)

    Vector search:
      - Default: brute-force cosine similarity (fast enough for <= 2000 records)
      - Optional: FAISS IVF index for sources with > 1000 success records

    Batch operations:
      - On startup: load embeddings.npz into memory for active sources
      - On record: append new embedding to in-memory array + save to npz
      - On eviction: rebuild embeddings.npz (remove evicted vectors)
    """
```

### 11.12 Schema Drift Detection

When a source's schema changes (tables added/removed, columns renamed), cached records that reference stale schema elements must be invalidated.

```
Schema drift detection:
  1. On each source connection, compute current schema_hash
  2. Compare against schema_hashes.json entries
  3. If mismatch detected:
     a. Mark affected SuccessRecords as stale (excluded from exact-match cache)
     b. Keep them available for template matching (at reduced score: −0.20)
     c. Log schema drift event for user visibility
     d. Records auto-revalidate if schema reverts (hash matches again)
  4. Never auto-delete records on drift — schema may revert, and the code
     patterns are still valuable as templates even with column renames
```

### 11.13 Configuration

```yaml
# In mcpdb.yaml

experience:
  enabled: true
  storage_dir: ~/.mcpdb/experience
  embedding_provider: auto              # auto | anthropic | google | openai | none
  max_success_records: 2000             # Per source
  max_failure_records: 500
  max_strategy_records: 200
  cache_max_age_days: 30                # Exact-match cache TTL
  template_max_age_days: 90             # Template matching TTL
  anti_pattern_min_occurrences: 2       # Min failures before injecting warning
  cross_dialect_promotion_threshold: 2  # Sources before promoting to dialect-level
  similarity_threshold_high: 0.85       # Template injection threshold
  similarity_threshold_medium: 0.65     # Example injection threshold
```

### 11.14 MCP Tools for Experience Management

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_experience_stats` | Show learning stats for a source | `source_id: str` |
| `clear_experience` | Clear all experience for a source | `source_id: str`, `confirm: bool` |
| `vote_response` | Upvote/downvote the last response | `vote: +1\|-1` |
| `list_cached_queries` | List exact-match cached queries for a source | `source_id: str`, `limit?: int` |
| `invalidate_cache_entry` | Remove a specific cache entry | `record_id: str` |

---

## 12. MCP Server — Tools, Resources & Prompts

### 12.1 Overview

The MCP server is the **primary external API** for MCPDB. It exposes three MCP entity types:

| MCP Entity | Count | Purpose |
|------------|-------|---------|
| **Tools** | 44 | Callable operations (query, analyze, generate, export) |
| **Resources** | 10 | Readable context (schemas, ERDs, profiles, history) |
| **Prompts** | 6 | Reusable prompt templates for guided workflows |

All three entity types support MCP's standard list/get protocol, making them discoverable by any MCP-compatible client. The key architectural principle: **every capability the internal agent uses MUST also be exposed as a standalone tool** so that clients can orchestrate their own pipelines (see Section 3.2 Dual-Mode Architecture).

### 12.1.1 Progressive Tool Disclosure (solving the 44-tool problem)

44 tools is too many for any client LLM to handle at once. Tool selection accuracy degrades past ~15 tools, and descriptions alone consume 5k+ tokens. The server addresses this via **context-aware tool filtering**:

```
Tool visibility tiers:

TIER 1 — Always visible (core, 12 tools):
  connect_database, load_csv_files, load_excel_file, list_sources,
  get_source_schema, execute_sql, execute_python, ask_question,
  list_artifacts, get_artifact, suggest_followups, vote_response

TIER 2 — Visible when database/CSV sources are active (+8 tools):
  search_schema, profile_table, render_erd, get_table_sample,
  cross_source_query, validate_sql, explain_query, generate_sql

TIER 3 — Visible when Excel sources are active (+6 tools):
  list_sheets, read_excel_range, analyze_sheet_structure,
  extract_excel_table, explain_formula, get_formula_dependencies

TIER 4 — Visible during active execution (+3 tools):
  cancel_execution, submit_strategy, add_context

TIER 5 — Visible on demand / advanced (+13 tools):
  profile_column, find_relationships, suggest_joins, compare_schemas,
  execute_sql_chunked, summarize_results, suggest_visualization,
  estimate_query_cost, export_conversation, remove_source,
  get_experience_stats, clear_experience, list_cached_queries,
  invalidate_cache_entry, get_similar_queries
```

The server implements this via MCP's `tools/list` response — returning only tools relevant to the current session state. When state changes (source connected, execution starts), the server emits `notifications/tools/list_changed` so the client refreshes its tool list. A client that wants ALL tools can set `"tool_filter": "all"` in initialization options.

### 12.2 MCP Transport Options

```python
# mcpdb/mcp/server.py

class MCPDBServer:
    """MCP server exposing MCPDB tools, resources, and prompts.

    Transport options:
      - stdio: For CLI and Claude Desktop integration
      - SSE (Server-Sent Events): For web clients
      - Streamable HTTP: For scalable deployments (MCP 2025-03-26 spec)

    The server manages a SessionManager instance and registers
    all tools, resources, and prompts with the MCP protocol handler.
    Capability negotiation at initialization declares supported features.
    """
```

### 12.3 Complete Tool Inventory (44 tools, 10 categories)

Every tool has a JSON Schema for inputs/outputs. Tools marked with ★ are also used internally by the LangGraph agent — the agent composes the SAME tools the client can call directly.

#### Category 1: Session Management (6 tools)

| # | Tool | Description | Parameters |
|---|------|-------------|------------|
| 1 | `connect_database` | Connect to a SQL database | `connection_string: str`, `display_name?: str` |
| 2 | `load_csv_files` | Load one or more CSV files | `file_paths: list[str]`, `options?: CsvLoadOptions` |
| 3 | `load_excel_file` | Load an Excel workbook | `file_path: str` |
| 4 | `list_sources` | List all active data sources with metadata | — |
| 5 | `remove_source` | Disconnect/unload a source | `source_id: str` |
| 6 | `get_source_schema` | Get full schema text for a source | `source_id: str`, `format?: "text"\|"json"` |

#### Category 2: Schema Discovery & Exploration (7 tools) — NEW

These tools enable **independent, incremental schema exploration** — a client (or the agent's planning node) can discover what's available without loading the entire schema into context.

| # | Tool | Description | Parameters |
|---|------|-------------|------------|
| 7 | `search_schema` ★ | Search tables/columns by keyword or pattern | `query: str`, `source_id?: str`, `search_in?: "tables"\|"columns"\|"both"` |
| 8 | `profile_table` ★ | Data profiling: row count, column stats (nulls, uniques, min/max, top values), size estimate | `table_name: str`, `source_id?: str`, `sample_size?: int` |
| 9 | `profile_column` | Detailed column analysis: distribution histogram, percentiles, pattern detection | `table_name: str`, `column_name: str`, `source_id?: str` |
| 10 | `find_relationships` | Discover FK relationships + inferred joins (matching column names/types) | `source_id: str`, `table_name?: str` |
| 11 | `suggest_joins` | Given 2+ tables, suggest optimal join paths with confidence | `tables: list[str]`, `source_id?: str` |
| 12 | `render_erd` ★ | Generate Mermaid ER diagram for selected tables (or all) | `source_id: str`, `tables?: list[str]`, `include_columns?: bool` |
| 13 | `compare_schemas` | Compare schemas of two sources (table overlap, type differences) | `source_id_a: str`, `source_id_b: str` |

**`render_erd` detail**: Generates a Mermaid `erDiagram` block showing tables, columns (with types and PK/FK markers), and relationships. Output is a Mermaid string that any client can render. Internally used by the planning node to understand data structure before generating SQL.

```
Example output (Mermaid ER diagram):

erDiagram
    CUSTOMERS {
        int id PK
        varchar name
        date created_at
    }
    ORDERS {
        int id PK
        int customer_id FK
        decimal total
        date order_date
    }
    CUSTOMERS ||--o{ ORDERS : "has"
```

#### Category 3: Database & CSV Querying (6 tools)

| # | Tool | Description | Parameters |
|---|------|-------------|------------|
| 14 | `execute_sql` ★ | Run SQL on a database or CSV source | `query: str`, `source_id?: str`, `max_rows?: int` |
| 15 | `execute_sql_chunked` ★ | Run SQL in chunks for large tables | `query: str`, `chunk_column: str`, `source_id?: str`, `chunk_size?: int` |
| 16 | `get_table_sample` ★ | Get sample rows from a table | `table_name: str`, `source_id?: str`, `limit?: int` |
| 17 | `cross_source_query` ★ | Query across multiple sources via DuckDB federation | `query: str`, `source_mapping: dict[str, str]` |
| 18 | `validate_sql` | Syntax-check SQL without executing (parse + schema validate) | `query: str`, `source_id?: str` |
| 19 | `explain_query` | Return EXPLAIN/execution plan output | `query: str`, `source_id?: str` |

#### Category 4: Excel-Specific Tools (6 tools)

| # | Tool | Description | Parameters |
|---|------|-------------|------------|
| 20 | `list_sheets` ★ | List all sheets in a workbook with dimensions | `source_id: str` |
| 21 | `read_excel_range` ★ | Read cells with values and/or formulas | `source_id: str`, `sheet: str`, `range?: str`, `include_formulas?: bool` |
| 22 | `analyze_sheet_structure` ★ | Detect tables, layout regions, merged cells | `source_id: str`, `sheet: str` |
| 23 | `extract_excel_table` ★ | Extract rectangular region as DataFrame table | `source_id: str`, `sheet: str`, `range: str` |
| 24 | `explain_formula` ★ | Explain what a formula does in plain language | `source_id: str`, `sheet: str`, `cell: str` |
| 25 | `get_formula_dependencies` ★ | Show formula dependency chain as a tree | `source_id: str`, `sheet: str`, `cell: str` |

#### Category 5: LLM-Assisted Analysis (6 tools)

These are the tools where the server's LLM generates code or text. In **Tool Mode**, clients can call them individually. In **Agent Mode**, the `ask_question` tool orchestrates them internally via LangGraph.

| # | Tool | Description | Parameters |
|---|------|-------------|------------|
| 26 | `execute_python` ★ | Run Python code in sandbox (pandas, matplotlib, seaborn available) | `code: str` |
| 27 | `ask_question` | **Agent Mode entry point**: full LangGraph pipeline (classify → plan → execute → debug → synthesize) | `question: str`, `mode?: "auto"\|"quick"\|"simple"\|"extended"\|"deep"`, `deep_analysis?: bool` |
| 28 | `generate_sql` ★ | LLM generates SQL for a question WITHOUT executing it. Returns SQL + explanation. | `question: str`, `source_id?: str` |
| 29 | `summarize_results` ★ | LLM summarizes a result set (last query output or specified artifact) | `artifact_id?: str`, `instructions?: str` |
| 30 | `suggest_visualization` ★ | LLM suggests chart type + generates Python code for the last result | `artifact_id?: str`, `chart_type?: str` |
| 31 | `estimate_query_cost` ★ | Estimate cost/risk of a SQL query before execution (row count, time, scan type) | `query: str`, `source_id?: str` |

#### Category 6: Execution Control (3 tools)

| # | Tool | Description | Parameters |
|---|------|-------------|------------|
| 32 | `cancel_execution` | Cancel in-progress analysis, get partial results | `reason?: str` |
| 33 | `submit_strategy` | Choose strategy for cost-gated query | `strategy: "SAMPLE"\|"FULL"\|"CANCEL"`, `custom_instructions?: str` |
| 34 | `add_context` | Inject additional context mid-execution | `message: str` |

#### Category 7: Output & Export (3 tools)

| # | Tool | Description | Parameters |
|---|------|-------------|------------|
| 35 | `export_conversation` | Export as PDF/HTML/notebook | `format: str`, `path?: str` |
| 36 | `list_artifacts` | List generated tables/charts/grids | — |
| 37 | `get_artifact` | Get a specific artifact by ID | `artifact_id: str` |

#### Category 8: Experience & Learning (5 tools — see Section 11)

| # | Tool | Description | Parameters |
|---|------|-------------|------------|
| 38 | `get_experience_stats` | Show learning stats for a source (cache hits, records, top patterns) | `source_id: str` |
| 39 | `clear_experience` | Clear all experience for a source | `source_id: str`, `confirm: bool` |
| 40 | `vote_response` | Upvote/downvote the last response (feeds learning system) | `vote: +1\|-1` |
| 41 | `list_cached_queries` | List exact-match cached queries | `source_id: str`, `limit?: int` |
| 42 | `invalidate_cache_entry` | Remove a specific cache entry | `record_id: str` |

#### Category 9: Conversation Intelligence (2 tools) — NEW

| # | Tool | Description | Parameters |
|---|------|-------------|------------|
| 43 | `suggest_followups` ★ | Generate 3-5 contextual follow-up questions based on conversation + last result | `count?: int` |
| 44 | `get_similar_queries` | Search experience store for similar past questions and their answers | `question: str`, `source_id?: str`, `top_k?: int` |

**`suggest_followups` detail**: This is NOT a disconnected utility — it is a first-class MCP tool exposed to all clients and used by the agent's synthesis node. After every successful analysis, the agent calls `suggest_followups` and includes the results in the response. Clients display these as clickable next-step suggestions.

Generation strategy:
1. Analyze the last result (what dimensions exist, what wasn't explored)
2. Consider conversation history (what was already asked)
3. Apply domain awareness (detected from schema — e.g., time-series → suggest trend analysis)
4. Use experience store (what did other users ask next in similar contexts)
5. If LLM available: generate via prompt. Fallback: rule-based templates.

#### Tool Count Summary

| Category | Tools | New vs Ported |
|----------|-------|---------------|
| Session Management | 6 | Ported |
| Schema Discovery & Exploration | 7 | **NEW** |
| Database & CSV Querying | 6 | 4 ported + 2 new |
| Excel-Specific | 6 | Ported |
| LLM-Assisted Analysis | 6 | 2 ported + 4 **NEW** |
| Execution Control | 3 | Ported |
| Output & Export | 3 | Ported |
| Experience & Learning | 5 | **NEW** |
| Conversation Intelligence | 2 | **NEW** |
| **Total** | **44** | **15 new tools** |

### 12.4 MCP Resources (10 resources)

Resources are **read-only, URI-addressable context** that clients can fetch or subscribe to. Unlike tools, resources don't perform operations — they provide structured data for the client's LLM to reason about.

| # | URI Pattern | Description | Content Type |
|---|-------------|-------------|--------------|
| 1 | `source://{source_id}/schema` | Full schema (tables, columns, types, PKs, FKs, indexes) | `application/json` |
| 2 | `source://{source_id}/tables` | Table list with row counts and size tags | `application/json` |
| 3 | `source://{source_id}/table/{table_name}` | Single table detail: columns, sample rows, stats | `application/json` |
| 4 | `source://{source_id}/erd` | Mermaid ER diagram for the source | `text/x-mermaid` |
| 5 | `source://{source_id}/profile` | Data profile summary (top-level stats for all tables) | `application/json` |
| 6 | `source://{source_id}/experience` | Experience stats: cache entries, success rate, top patterns | `application/json` |
| 7 | `source://{source_id}/dialect_rules` | SQL syntax rules for this source's dialect | `text/plain` |
| 8 | `session://sources` | All active sources with metadata and capabilities | `application/json` |
| 9 | `session://history` | Conversation history (messages + artifacts) | `application/json` |
| 10 | `session://artifacts` | All artifacts from current session | `application/json` |

**Resource subscriptions**: Clients can subscribe to resources via MCP's `resources/subscribe` to receive notifications when content changes (e.g., when a new source is connected or an artifact is created). The server emits `notifications/resources/updated` when:
- A source is connected/disconnected (affects resources 1-8)
- A query produces new artifacts (affects resource 10)
- Experience store is updated (affects resource 6)

```python
# Example: ERD resource implementation
@server.resource("source://{source_id}/erd")
async def get_source_erd(source_id: str) -> str:
    """Mermaid ER diagram for a connected data source."""
    source = session.get_source(source_id)
    tables = source.get_tables()
    relationships = source.get_relationships()
    return generate_mermaid_erd(tables, relationships)
```

### 12.5 MCP Prompts (6 prompts)

MCP prompts are **reusable, parameterized prompt templates** that clients discover via `prompts/list` and retrieve via `prompts/get`. The server returns pre-built messages that the client's LLM uses for guided workflows. This enables **Tool Mode orchestration** — the client's LLM receives a structured prompt telling it which MCPDB tools to call and in what order.

| # | Prompt Name | Description | Arguments |
|---|-------------|-------------|-----------|
| 1 | `explore_source` | Guided workflow for initial exploration of a new data source: discover schema, profile key tables, generate ERD, suggest first questions | `source_id: str` |
| 2 | `deep_table_analysis` | Comprehensive single-table analysis: profiling, distributions, anomalies, relationships, sample queries | `source_id: str`, `table_name: str` |
| 3 | `cross_source_report` | Compare or join data across multiple sources | `source_ids: list[str]`, `focus?: str` |
| 4 | `data_quality_audit` | Find nulls, duplicates, outliers, type mismatches, referential integrity issues | `source_id: str`, `tables?: list[str]` |
| 5 | `generate_dashboard` | Generate a multi-chart dashboard for key metrics | `source_id: str`, `focus?: str` |
| 6 | `excel_workbook_analysis` | Guided Excel exploration: sheet structure, formula map, data extraction, cross-sheet relationships | `source_id: str` |

**Example prompt implementation**:

```python
@server.prompt("explore_source")
async def explore_source_prompt(source_id: str) -> list[Message]:
    """Return a multi-step prompt guiding the client's LLM through source exploration."""
    source = session.get_source(source_id)
    schema_summary = source.get_context_description()

    return [
        UserMessage(content=f"""You are exploring a new data source. Here is its schema:

{schema_summary}

Follow these steps using the available MCPDB tools:

1. Call `render_erd` to visualize the table relationships
2. Call `profile_table` on the 3 largest tables to understand data distributions
3. Call `find_relationships` to discover joins
4. Based on what you learn, suggest 5 interesting analytical questions
5. Call `suggest_followups` to generate context-aware next steps

Present your findings as a structured exploration report with:
- ERD diagram (Mermaid)
- Key tables summary (rows, columns, notable patterns)
- Relationship map
- Suggested questions ranked by analytical value
""")
    ]
```

**Why prompts matter**: In Tool Mode, the client's LLM doesn't inherently know HOW to explore a database. MCP prompts provide expert-crafted workflows that guide the client through multi-step analysis using MCPDB's tools. This is the bridge between "here are 44 tools" and "here's how to use them effectively."

### 12.6 MCP Tool Registration

```python
# mcpdb/mcp/tools.py

from mcp.server import Server
from mcp.types import Tool, TextContent, ImageContent

def register_all(server: Server, session: SessionManager):
    """Register all 44 tools, 10 resources, and 6 prompts.

    Tools are organized into modules matching their categories:
      mcpdb/mcp/tools/
        session.py          # Category 1: connect, load, list, remove
        discovery.py        # Category 2: search_schema, profile, ERD, relationships
        querying.py         # Category 3: execute_sql, validate, explain
        excel.py            # Category 4: sheets, ranges, formulas
        analysis.py         # Category 5: ask_question, generate_sql, summarize
        control.py          # Category 6: cancel, strategy, add_context
        export.py           # Category 7: export, artifacts
        experience.py       # Category 8: stats, vote, cache
        conversation.py     # Category 9: followups, similar queries

    Each module exports a register_*(server, session) function.
    """
    from mcpdb.mcp.tools import (
        session as session_tools,
        discovery, querying, excel, analysis,
        control, export, experience, conversation,
    )
    for module in [session_tools, discovery, querying, excel, analysis,
                   control, export, experience, conversation]:
        module.register(server, session)

    from mcpdb.mcp import resources, prompts
    resources.register(server, session)
    prompts.register(server, session)
```

### 12.7 MCP Resources

```python
# mcpdb/mcp/resources.py — registers all 10 resources

@server.resource("source://{source_id}/schema")
async def get_source_schema(source_id: str) -> str:
    """Full schema for a connected data source."""
    return session.get_source(source_id).get_schema_json()

@server.resource("source://{source_id}/erd")
async def get_source_erd(source_id: str) -> str:
    """Mermaid ER diagram for a connected data source."""
    return session.get_source(source_id).render_erd()

@server.resource("session://sources")
async def get_session_sources() -> str:
    """All active data sources in the current session."""
    return json.dumps([m.to_dict() for m in session.list_sources()])

# ... (all 10 resources follow the same pattern)
```

---

## 13. LLM Integration Layer

### 13.1 Provider Abstraction

```python
# mcpdb/llm/provider.py

class LLMProvider(ABC):
    """Abstract LLM provider interface.

    All methods are async. Streaming is mandatory — generate() internally
    collects the stream, but stream() is the primary interface used by
    agent nodes for real-time thinking visibility.
    """

    @abstractmethod
    async def generate(self, messages: list[BaseMessage], **kwargs) -> AIMessage:
        """Non-streaming call. Internally calls stream() and collects."""
        ...

    @abstractmethod
    async def stream(self, messages: list[BaseMessage], **kwargs) -> AsyncIterator[StreamChunk]:
        """Streaming call. Yields StreamChunk(text, usage?) for each token batch.

        This is the primary interface. Agent nodes use stream() via
        stream_llm_call() (Section 10.2.1) to emit llm/token events.
        """
        ...

    @abstractmethod
    async def generate_json(self, messages: list[BaseMessage], schema: dict, **kwargs) -> dict:
        """Generate structured JSON output. Uses streaming internally."""
        ...


@dataclass
class StreamChunk:
    text: str                          # Token text delta
    usage: TokenUsage | None = None    # Only set on the final chunk


class AnthropicProvider(LLMProvider):
    """Claude via Anthropic API (default). Uses anthropic.AsyncClient."""
    def __init__(self, model: str = "claude-sonnet-4-6", api_key: str = ""): ...


class GoogleProvider(LLMProvider):
    """Gemini via Google AI. Uses google.genai.aio."""
    def __init__(self, model: str = "gemini-2.5-pro", api_key: str = ""): ...


class OpenAIProvider(LLMProvider):
    """GPT-4 / o-series via OpenAI API. Uses openai.AsyncOpenAI."""
    def __init__(self, model: str = "gpt-4o", api_key: str = ""): ...
```

### 13.2 Model Configuration

```python
@dataclass
class ModelConfig:
    """LLM configuration for the agent."""
    reasoning_provider: str = "anthropic"     # For planning, classification, debugging
    reasoning_model: str = "claude-sonnet-4-6"
    fast_provider: str = "anthropic"           # For synthesis, recommendations
    fast_model: str = "claude-haiku-4-5-20251001"
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout: int = 120
```

### 13.3 LLM Cost Tracking & Budget

Every LLM call is metered. The system tracks tokens and estimated cost per execution.

```python
@dataclass
class LLMUsage:
    """Accumulated LLM usage for a single ask_question execution."""
    calls: int = 0                      # Number of LLM API calls
    input_tokens: int = 0               # Total input tokens
    output_tokens: int = 0              # Total output tokens
    estimated_cost_usd: float = 0.0     # Estimated cost (based on model pricing)
    breakdown: list[dict] = field(default_factory=list)  # Per-call detail
```

**Cost estimates per thinking mode** (using Claude Sonnet at $3/$15 per M tokens):

| Mode | LLM Calls | Typical Input Tokens | Typical Cost |
|------|-----------|---------------------|-------------|
| Quick | 2-3 | 3-8K | $0.01-0.03 |
| Simple | 5-8 | 15-30K | $0.05-0.15 |
| Extended | 8-15 | 30-60K | $0.10-0.30 |
| Optimization | 6-10 | 20-40K | $0.08-0.20 |
| Deep Analysis | 20-80 | 80-300K | $0.30-1.50 |

**Budget enforcement**:
- `llm.budget_per_question_usd` config option (default: $2.00, 0 = unlimited)
- Before each LLM call, check accumulated cost against budget
- If budget would be exceeded: emit `budget_warning` streaming event, gracefully
  synthesize partial results, report to user what was completed
- Deep Analysis mode checks budget between investigations — stops adding new ones
  if remaining budget < estimated cost of one investigation

**Cost visibility**: `LLMUsage` is included in every `ask_question` response and
emitted as a `usage_update` streaming event after each LLM call. The frontend
displays running cost in the execution monitor.

### 13.4 Credential Handling

**Connection strings MUST NOT leak through the system**:

1. **On connect**: The raw connection string is used once to create the SQLAlchemy
   engine, then the password portion is redacted from all in-memory representations.
   `SourceMetadata.connection_info` stores only `host:port/database` (no credentials).
2. **MCP message logs**: The `connect_database` tool redacts the password from its
   response. If MCP transport logging is enabled, credential parameters are masked
   with `***`.
3. **Experience store**: `SourceFingerprint` hashes `host:port/database` — never
   the password. The original connection string is NOT stored anywhere on disk.
4. **Reconnection**: If a pooled connection drops, SQLAlchemy's engine (which holds
   the connection string in memory) reconnects automatically. The string is only in
   the engine's process memory, never serialized.
5. **Claude Desktop config**: The spec recommends using environment variable references
   (`"connection_string": "$POSTGRES_URL"`) rather than inline credentials.

### 13.5 Async/Sync Threading Model

The MCP server is **async** (asyncio). Database and LLM operations are bridged to never block the event loop.

**Async/sync boundary map**:

| Component | Execution Model | How It Connects to Async Event Loop |
|-----------|----------------|-------------------------------------|
| MCP request handlers | `async` | Native asyncio coroutines. Multiple MCP requests processed concurrently. |
| LLM streaming calls | `async` | Provider SDKs use `async for chunk in stream`. Tokens emitted as `llm/token` events between `await` points. Cancellation checked per chunk. |
| SQL query execution | `sync` (SQLAlchemy) | Dispatched via `run_in_executor(thread_pool)`. Wrapped by `CancellableQueryRunner` (Section 10.3.2) which monitors cancellation in a parallel asyncio task. |
| Python sandbox | `subprocess` | Launched via `asyncio.create_subprocess_exec()`. Non-blocking. `SIGTERM`/`SIGKILL` for cancellation. |
| EXPLAIN queries | `sync` | Same thread pool as SQL. Lightweight (planner only, no execution). |
| Experience store I/O | `sync` | Dispatched via `run_in_executor`. File I/O and embedding search are fast (<50ms typical). |
| CallbackManager.emit() | Thread-safe, non-blocking | Events are enqueued to an `asyncio.Queue`. A dedicated async task drains the queue and dispatches to MCP notification handlers and WebSocket listeners. |

**Thread pool sizing**: `ThreadPoolExecutor(max_workers=pool_size + 2)` — `pool_size` workers for SQL (matching SQLAlchemy connection pool), +1 for EXPLAIN queries, +1 for experience store I/O. This prevents SQL execution from starving EXPLAIN or experience lookups.

**Critical non-blocking guarantee**: The asyncio event loop is NEVER blocked by any operation. This means:
- `cancel_execution` tool calls are processed immediately, even while a SQL query is running in the thread pool
- `add_context` messages are enqueued immediately
- `get_session_status` returns the current state without waiting for any in-progress operation
- Streaming events (`llm/token`, `step/progress`) are emitted without delay
- Multiple concurrent sessions are supported (each `ask_question` runs its own coroutine)

### 13.6 Prompt Templates

The prompt system is parameterized by source type. See [Appendix A](#appendix-a-prompt-templates) for full templates.

Key adaptations from dbtalk:
- **Classification prompt**: Enhanced with multi-source awareness + `key_entities` output for schema subsetting
- **Planning prompt**: Source-specific action types (sql, python, excel_read, etc.) + experience templates/anti-patterns
- **System prompt**: Includes relevant source context (subsetted, not full dump), Excel-specific guidelines
- **Debug prompt**: Source-aware error analysis + experience-based fix suggestions

---

## 14. Python Execution Sandbox

### 14.1 Overview

```python
# mcpdb/sandbox/executor.py

class PythonSandbox:
    """Sandboxed Python execution environment.

    Pre-injected variables:
      - pd (pandas)
      - np (numpy)
      - plt (matplotlib.pyplot)
      - sns (seaborn)
      - df: DataFrame from last query/extraction
      - db_query(sql, source_id?): Execute SQL on a source
      - read_excel(source_id, sheet, range?): Read Excel cells
      - result: Set this to return output

    Security (enforced via subprocess isolation, NOT exec() with restricted globals):
      - Execution in a **separate subprocess** with:
        a. RestrictedPython compilation (blocks ast nodes: Import, ImportFrom unless
           in allowlist, Attribute access to dunder methods blocked)
        b. Subprocess timeout via signal.alarm (hard kill after timeout+5s)
        c. Resource limits via resource.setrlimit: RLIMIT_AS for memory,
           RLIMIT_CPU for CPU time, RLIMIT_NOFILE=0 for filesystem
        d. seccomp profile (Linux) or sandbox-exec (macOS) blocking
           network syscalls (connect, bind, listen) and filesystem writes
      - Import allowlist: pandas, numpy, matplotlib, seaborn, math, datetime,
        collections, itertools, functools, statistics, decimal, json, re, textwrap
      - db_query() helper enforces read-only: wraps source.execute_query()
        which uses read-only connections (SET SESSION CHARACTERISTICS AS
        TRANSACTION READ ONLY for PostgreSQL, etc.)
      - Memory limit: 512MB per execution (configurable)
      - Timeout: 60s default (configurable)

    Output capture:
      - stdout is captured
      - matplotlib figures are captured as base64 PNG
      - DataFrames are serialized as artifacts
      - Scalars/strings are returned as text
    """

    def execute(self, code: str, context: dict[str, Any],
                timeout: int = 60) -> SandboxResult: ...
```

### 14.2 SandboxResult

```python
@dataclass
class SandboxResult:
    success: bool
    output: str                    # Captured stdout
    result_value: Any              # Value of 'result' variable
    artifacts: list[dict]          # Generated tables/charts
    error: str | None              # Error traceback if failed
    execution_time_ms: int
    memory_delta_mb: float
```

---

## 15. Frontend (Python UI)

### 15.1 Technology Choice

The frontend is built with **NiceGUI** (https://nicegui.io) — a Python-native UI framework that:
- Renders as a modern web app (Vue.js + Quasar under the hood)
- Runs as a Python process (no Node.js, no npm)
- Supports real-time updates via WebSocket
- Has rich component library (tables, charts, file upload, markdown)
- Can be packaged as a standalone app

**Alternative**: Panel (https://panel.holoviz.org) if more data-science-oriented widgets are needed.

### 15.2 UI Components

```
mcpdb/ui/
├── __init__.py
├── app.py                    # Main application entry point
├── pages/
│   ├── chat.py               # Main chat interface
│   ├── sources.py            # Source management panel
│   └── settings.py           # Configuration page
├── components/
│   ├── message_renderer.py   # Render chat messages (markdown, LaTeX, tables, charts)
│   ├── artifact_viewer.py    # Display tables and charts
│   ├── source_panel.py       # Source connection/upload widgets
│   ├── execution_monitor.py  # Step-by-step execution display
│   ├── schema_viewer.py      # Schema/structure browser
│   ├── excel_viewer.py       # Excel cell grid viewer (shows formulas, merged cells)
│   ├── cost_gate_dialog.py   # Strategy selection dialog
│   └── export_dialog.py      # Export format selection
├── streaming.py              # WebSocket streaming handler
└── theme.py                  # UI theme and styling
```

### 15.3 Chat Page Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  MCPDB                              [Sources ▾] [Settings ⚙]   │
├──────────────┬──────────────────────────────────────────────────┤
│              │                                                  │
│  SOURCES     │  CHAT                                            │
│              │                                                  │
│  ┌─────────┐ │  ┌──────────────────────────────────────────┐    │
│  │ 🗄 mydb  │ │  │ User: Show me the top 10 customers       │    │
│  │ PostgreSQL│ │  │        by revenue                        │    │
│  │ 5 tables │ │  └──────────────────────────────────────────┘    │
│  └─────────┘ │                                                  │
│              │  ┌──────────────────────────────────────────┐    │
│  ┌─────────┐ │  │ 🤖 Assistant:                             │    │
│  │ 📄 sales │ │  │                                          │    │
│  │ CSV      │ │  │ ▸ Planning (3 steps)                     │    │
│  │ 2 files  │ │  │ ▸ Executing SQL...                       │    │
│  └─────────┘ │  │                                          │    │
│              │  │ ┌────────────────────────────────────┐    │    │
│  ┌─────────┐ │  │ │  customer  │ revenue    │ orders  │    │    │
│  │ 📊 budget│ │  │ │───────────┼────────────┼─────────│    │    │
│  │ Excel    │ │  │ │  Acme Corp│ $1,234,567 │    42   │    │    │
│  │ 3 sheets │ │  │ │  ...      │ ...        │   ...   │    │    │
│  └─────────┘ │  │ └────────────────────────────────────┘    │    │
│              │  │                                          │    │
│  [+ Add      │  │ Here are your top 10 customers...        │    │
│   Source]    │  └──────────────────────────────────────────┘    │
│              │                                                  │
│              │  ┌──────────────────────────────────────────┐    │
│              │  │ 💬 Ask a question about your data...      │    │
│              │  └──────────────────────────────────────────┘    │
├──────────────┴──────────────────────────────────────────────────┤
│  Execution: 3/3 steps complete │ 1.2s │ 📊 2 artifacts        │
└─────────────────────────────────────────────────────────────────┘
```

### 15.4 Source Connection Flows

**Database:**
```
[+ Add Source] → [Database] → Connection form:
  - Quick connect: paste connection string
  - Form mode: host, port, database, user, password, SSL
  - Test connection button
  - Auto-detect database type from URL
```

**CSV Files:**
```
[+ Add Source] → [CSV Files] → File picker / drag-drop:
  - Select multiple files
  - Preview detected settings (encoding, delimiter, headers)
  - Override options per file if needed
  - "Load" button → tables appear in sidebar
```

**Excel Files:**
```
[+ Add Source] → [Excel] → File picker:
  - Select .xlsx/.xlsm/.xls file
  - Preview: list of sheets with structure summary
  - "Load" button → sheets appear in sidebar
  - Click sheet → see structure analysis in side panel
```

### 15.5 Excel-Specific UI: Cell Grid Viewer

The Excel viewer is a specialized component that renders CellGrid data:

```
┌─────────────────────────────────────────────────────┐
│  budget.xlsx > Sheet1 "Annual Budget"    [Formulas] │
├─────────────────────────────────────────────────────┤
│     │  A          │  B          │  C         │  D   │
│  1  │ Department  │ Q1 Budget   │ Q2 Budget  │Total │
│  2  │ Engineering │ 500,000     │ 550,000    │=B2+C2│
│  3  │ Marketing   │ 200,000     │ 180,000    │=B3+C3│
│  4  │ Sales       │ 300,000     │ 320,000    │=B4+C4│
│  5  │             │             │            │      │
│  6  │ TOTAL       │ =SUM(B2:B4) │=SUM(C2:C4)│=SUM( │
│     │             │             │            │ D2:D4│
│     │             │             │            │)     │
├─────────────────────────────────────────────────────┤
│ Detected: 1 table (A1:D6), 5 formulas              │
│ Merged regions: none                                 │
└─────────────────────────────────────────────────────┘
```

Toggle between **Values** view and **Formulas** view. Merged cells are visually indicated.

### 15.6 Communication: UI ↔ Backend

The UI communicates with the MCP server via **WebSocket**:

```python
# UI startup
async def start():
    # Start MCP server in-process
    server = MCPDBServer(transport="websocket", port=8765)
    await server.start()

    # UI connects as MCP client
    client = MCPClient("ws://localhost:8765")
    await client.connect()

    # Tool calls go through MCP
    result = await client.call_tool("connect_database", {
        "connection_string": "postgresql://..."
    })
```

For streaming (execution progress, thinking steps), the server sends MCP **notifications**:
```python
@server.notification("execution/progress")
async def on_progress(step: int, total: int, message: str): ...

@server.notification("execution/artifact")
async def on_artifact(artifact: dict): ...
```

---

## 16. Configuration & Environment

### 16.1 Configuration File

```yaml
# mcpdb.yaml (or .env)

# LLM Configuration
llm:
  reasoning:
    provider: anthropic        # anthropic | google | openai
    model: claude-sonnet-4-6
    api_key: ${ANTHROPIC_API_KEY}
  fast:
    provider: anthropic
    model: claude-haiku-4-5-20251001
    api_key: ${ANTHROPIC_API_KEY}
  temperature: 0.0
  timeout: 120
  budget_per_question_usd: 2.00    # Max LLM spend per ask_question call (0 = unlimited)

# Server Configuration
server:
  transport: stdio              # stdio | sse | websocket
  host: localhost
  port: 8765

# Execution
execution:
  query_timeout: 30             # SQL query timeout (seconds)
  python_timeout: 60            # Python execution timeout (seconds)
  max_rows_display: 100         # Max rows returned per query
  read_only: true               # Only SELECT queries allowed

# Cost Gate
cost_gate:
  enabled: true
  auto_mode: false              # Auto-approve optimized queries
  large_table_threshold: 1000000  # Rows

# DuckDB (for CSV)
duckdb:
  memory_limit: 2GB
  threads: 4                    # 0 = auto (CPU count)

# Experience & Learning (per-source — see Section 11)
experience:
  enabled: true
  storage_dir: ~/.mcpdb/experience
  embedding_provider: auto            # auto | anthropic | google | openai | none
  max_success_records: 2000
  max_failure_records: 500
  max_strategy_records: 200
  cache_max_age_days: 30
  template_max_age_days: 90
  anti_pattern_min_occurrences: 2
  cross_dialect_promotion_threshold: 2
  similarity_threshold_high: 0.85
  similarity_threshold_medium: 0.65

# UI
ui:
  theme: dark
  port: 8080
```

### 16.2 Environment Variables

```bash
# Required (at least one LLM provider)
ANTHROPIC_API_KEY=sk-ant-...
# or
GOOGLE_API_KEY=...
# or
OPENAI_API_KEY=sk-...

# Optional
MCPDB_CONFIG=./mcpdb.yaml      # Config file path
MCPDB_LOG_LEVEL=INFO
MCPDB_EXPERIENCE_DIR=~/.mcpdb/experience
```

---

## 17. Project Structure

```
mcpdb/
├── pyproject.toml                    # Project metadata, dependencies, entry points
├── mcpdb.yaml                        # Default configuration
├── README.md
│
├── mcpdb/                            # Main package
│   ├── __init__.py
│   ├── __main__.py                   # CLI entry point
│   │
│   ├── sources/                      # Data Source Layer
│   │   ├── __init__.py
│   │   ├── base.py                   # DataSource, QueryableSource, SpreadsheetSource ABCs
│   │   ├── registry.py               # SourceRegistry
│   │   ├── erd_generator.py          # Mermaid ER diagram generation (used by render_erd tool + ERD resource)
│   │   │
│   │   ├── database/                 # Database sources
│   │   │   ├── __init__.py
│   │   │   ├── source.py             # DatabaseSource
│   │   │   ├── connector.py          # SQLAlchemy connection management
│   │   │   ├── schema_explorer.py    # Schema introspection
│   │   │   ├── query_optimizer.py    # Sampling, chunking
│   │   │   ├── cost_estimator.py     # Cost analysis
│   │   │   └── dialects/
│   │   │       ├── __init__.py
│   │   │       ├── base.py
│   │   │       ├── postgresql.py
│   │   │       ├── mysql.py
│   │   │       ├── sqlite.py
│   │   │       ├── mssql.py
│   │   │       └── oracle.py
│   │   │
│   │   ├── csv/                      # CSV sources
│   │   │   ├── __init__.py
│   │   │   ├── source.py             # CsvSource
│   │   │   ├── loader.py             # CSV detection & loading
│   │   │   └── duckdb_backend.py     # DuckDB session management
│   │   │
│   │   └── excel/                    # Excel sources
│   │       ├── __init__.py
│   │       ├── source.py             # ExcelSource
│   │       ├── workbook_reader.py    # openpyxl reading
│   │       ├── structure_analyzer.py # Layout detection
│   │       ├── cell_grid.py          # CellGrid data structure
│   │       ├── formula_analyzer.py   # Formula parsing & explanation
│   │       ├── table_extractor.py    # DataFrame extraction
│   │       └── multi_workbook.py     # Multi-file management
│   │
│   ├── agent/                        # LangGraph Agent Layer (Modes 1-5)
│   │   ├── __init__.py
│   │   ├── graph.py                  # Orchestrator graph (classify → route to subgraphs)
│   │   ├── state.py                  # AgentState TypedDict (shared across all modes)
│   │   ├── prompts.py                # All prompt templates (classification, planning, debug, synthesis, cost gate, blueprint, reasoning)
│   │   ├── callbacks.py              # StreamingEvent, CallbackManager (30+ event types)
│   │   ├── cancellation.py           # CancellationToken, CancelledException (graceful cancel)
│   │   ├── user_input_queue.py       # UserInputQueue (mid-execution context injection)
│   │   ├── deep_analysis.py          # Mode 5: Deep Analysis meta-loop (Blueprint, Investigation, MultistepState)
│   │   ├── recommendations.py        # Follow-up generation (domain analysis, LLM, experience-based — powers suggest_followups tool)
│   │   │
│   │   ├── nodes/                    # Graph nodes (shared + mode-specific)
│   │   │   ├── __init__.py           # NodeContext
│   │   │   ├── classify.py           # Multi-source classifier (routes to Modes 1-4)
│   │   │   ├── common.py             # Shared node factories (plan, execute, debug, synthesize, cost_check, strategy_gate)
│   │   │   └── validators.py         # Result validation (validate_answer, validate_result, replan)
│   │   │
│   │   └── subgraphs/               # Mode-specific subgraphs (Modes 1-4)
│   │       ├── quick.py              # Mode 1: Context Chat
│   │       ├── simple.py             # Mode 2: Quick Analysis
│   │       ├── optimization.py       # Mode 3: Heavy Query
│   │       └── extended.py           # Mode 4: Deep Analysis subgraph
│   │
│   ├── mcp/                          # MCP Server Layer (44 tools, 10 resources, 6 prompts)
│   │   ├── __init__.py
│   │   ├── server.py                 # MCP server setup, transport, capability negotiation
│   │   ├── tools/                    # Tool registrations (one module per category)
│   │   │   ├── __init__.py           # register_all() aggregator
│   │   │   ├── session.py            # Cat 1: connect, load, list, remove (6 tools)
│   │   │   ├── discovery.py          # Cat 2: search_schema, profile, ERD, relationships (7 tools)
│   │   │   ├── querying.py           # Cat 3: execute_sql, validate, explain (6 tools)
│   │   │   ├── excel.py              # Cat 4: sheets, ranges, formulas (6 tools)
│   │   │   ├── analysis.py           # Cat 5: ask_question, generate_sql, summarize (6 tools)
│   │   │   ├── control.py            # Cat 6: cancel, strategy, add_context (3 tools)
│   │   │   ├── export.py             # Cat 7: export, artifacts (3 tools)
│   │   │   ├── experience.py         # Cat 8: stats, vote, cache (5 tools)
│   │   │   └── conversation.py       # Cat 9: followups, similar queries (2 tools)
│   │   ├── resources.py              # 10 MCP resources (schema, ERD, profile, history, etc.)
│   │   ├── prompts.py                # 6 MCP prompts (explore, analyze, audit, etc.)
│   │   └── notifications.py          # Streaming event notifications
│   │
│   ├── llm/                          # LLM Provider Layer
│   │   ├── __init__.py
│   │   ├── provider.py               # Abstract + concrete providers
│   │   └── config.py                 # Model configuration
│   │
│   ├── sandbox/                      # Python Execution Sandbox
│   │   ├── __init__.py
│   │   ├── executor.py               # Sandboxed execution
│   │   └── security.py               # Import restrictions, resource limits
│   │
│   ├── experience/                   # Per-Source Experience & Learning (Section 11)
│   │   ├── __init__.py
│   │   ├── fingerprint.py            # SourceFingerprint (stable source identity)
│   │   ├── records.py                # SuccessRecord, FailureRecord, StrategyRecord, CodeStep
│   │   ├── store.py                  # ExperienceStore (per-source JSONL + embeddings storage)
│   │   ├── cache.py                  # ExactMatchCache (O(1) intent_hash → cached response)
│   │   ├── retriever.py              # ExperienceRetriever (semantic search, template matching)
│   │   ├── recorder.py               # ExperienceRecorder (write records on success/failure)
│   │   ├── embeddings.py             # EmbeddingService (provider-agnostic, vector search)
│   │   └── dialect_patterns.py       # Cross-source dialect-level knowledge transfer
│   │
│   ├── session.py                    # SessionManager
│   │
│   └── ui/                           # Frontend
│       ├── __init__.py
│       ├── app.py                    # Main UI application
│       ├── pages/
│       │   ├── chat.py
│       │   ├── sources.py
│       │   └── settings.py
│       ├── components/
│       │   ├── message_renderer.py
│       │   ├── artifact_viewer.py
│       │   ├── source_panel.py
│       │   ├── execution_monitor.py
│       │   ├── schema_viewer.py
│       │   ├── excel_viewer.py
│       │   ├── cost_gate_dialog.py
│       │   └── export_dialog.py
│       ├── streaming.py
│       └── theme.py
│
└── tests/
    ├── conftest.py                   # Shared fixtures
    ├── unit/
    │   ├── sources/
    │   │   ├── test_database_source.py
    │   │   ├── test_csv_source.py
    │   │   ├── test_excel_source.py
    │   │   ├── test_csv_loader.py
    │   │   ├── test_structure_analyzer.py
    │   │   ├── test_formula_analyzer.py
    │   │   └── test_cell_grid.py
    │   ├── agent/
    │   │   ├── test_classify.py
    │   │   ├── test_planning.py
    │   │   └── test_execution.py
    │   ├── experience/
    │   │   ├── test_fingerprint.py
    │   │   ├── test_cache.py
    │   │   ├── test_retriever.py
    │   │   ├── test_recorder.py
    │   │   └── test_store.py
    │   ├── mcp/
    │   │   └── test_tools.py
    │   └── sandbox/
    │       └── test_executor.py
    ├── integration/
    │   ├── test_database_e2e.py
    │   ├── test_csv_e2e.py
    │   ├── test_excel_e2e.py
    │   ├── test_cross_source.py
    │   └── test_mcp_server.py
    └── fixtures/
        ├── sample.csv
        ├── multi_table.xlsx
        ├── formulas.xlsx
        ├── merged_cells.xlsx
        ├── non_rectangular.xlsx
        └── test.db
```

---

## 18. Data Models & Type Contracts

### 18.1 Artifact Types

```python
@dataclass
class Artifact:
    """A renderable output produced during analysis."""
    id: str                     # Unique artifact ID
    type: Literal["table", "chart", "text", "cell_grid", "error"]
    title: str
    data: dict[str, Any]        # Type-specific payload
    source_id: str | None       # Which source produced this
    step_number: int | None     # Which execution step
    timestamp: float


# Table artifact data:
{
    "columns": ["name", "value"],
    "rows": [["Alice", 42], ["Bob", 37]],
    "truncated": false,
    "total_rows": 2
}

# Chart artifact data:
{
    "image_base64": "iVBOR...",
    "format": "png",
    "width": 800,
    "height": 600
}

# CellGrid artifact data:
{
    "sheet": "Sheet1",
    "range": "A1:D6",
    "cells": [[{"value": "Dept", "formula": null, ...}, ...], ...],
    "merged_regions": [{"min_row": 1, "min_col": 1, "max_row": 1, "max_col": 3}]
}
```

### 18.2 Execution Log Entry

```python
@dataclass
class ExecutionLogEntry:
    step_number: int
    action: str                 # "sql", "python", "excel_read", etc.
    source_id: str | None
    code: str                   # SQL/Python code or operation description
    status: Literal["success", "error", "timeout", "skipped"]
    result_preview: str         # First 200 chars of result
    time_ms: int
    memory_delta_mb: float
    artifacts_produced: list[str]  # Artifact IDs
    error: str | None
```

### 18.3 Plan Schema

```python
{
    "analysis": "Understanding of user's question",
    "approach": "High-level strategy",
    "target_sources": ["source_id_1", "source_id_2"],
    "requires_cross_source": false,
    "steps": [
        {
            "step_number": 1,
            "action": "sql",           # sql | python | excel_read | excel_structure |
                                        # excel_formula | excel_extract | cross_query |
                                        # schema | sample
            "source_id": "db_1",
            "description": "Get top customers by revenue",
            "code": "SELECT c.name, SUM(o.total) as revenue FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.name ORDER BY revenue DESC LIMIT 10"
        },
        {
            "step_number": 2,
            "action": "python",
            "description": "Create bar chart of results",
            "code": "plt.figure(figsize=(10,6))\nplt.bar(df['name'], df['revenue'])\n..."
        }
    ]
}
```

### 18.4 Experience Records (see Section 11 for full specification)

```python
@dataclass
class SuccessRecord:
    """A successfully executed and validated analysis — cached for reuse."""
    id: str
    timestamp: float
    source_fingerprint: str
    question: str
    question_embedding: list[float]
    intent_hash: str                    # Exact-match cache key
    mode: str
    plan_json: dict | None
    steps: list[CodeStep]
    synthesis: str
    artifacts: list[str]
    schema_hash: str
    tables_used: list[str]
    columns_used: list[str]
    feedback_score: int                 # +1/-1/0
    execution_time_ms: int
    error_count: int
    reuse_count: int

@dataclass
class FailureRecord:
    """A failed execution — anti-pattern for future avoidance."""
    id: str
    timestamp: float
    source_fingerprint: str
    question: str
    question_embedding: list[float]
    mode: str
    failed_code: str
    error_message: str
    error_category: str
    root_cause: str
    fix_code: str | None
    fix_explanation: str | None
    tables_involved: list[str]

@dataclass
class StrategyRecord:
    """Cost-gating strategy decision and outcome."""
    id: str
    timestamp: float
    source_fingerprint: str
    question: str
    question_embedding: list[float]
    tables_involved: list[str]
    estimated_rows: int
    strategy_chosen: str
    sql_rewrite: str | None
    outcome: str
    execution_time_ms: int
    feedback_score: int
```

---

## 19. Error Handling Strategy

### 19.1 Error Categories

| Category | Examples | Recovery |
|----------|----------|----------|
| Connection | DB unreachable, timeout, auth failure | Retry with backoff (3 attempts) |
| Query syntax | Invalid SQL, wrong column names | LLM debug → fix → retry (3 attempts) |
| Query timeout | Statement timeout on large scan | Suggest optimization strategy |
| Python error | Runtime error in sandbox | LLM debug → fix → retry (3 attempts) |
| File error | CSV encoding issue, corrupt Excel | Report clearly, suggest alternatives |
| LLM error | API timeout, rate limit | Retry with backoff, fallback to fast model |
| Resource error | Out of memory, disk full | Report, suggest reducing scope |

### 19.2 Debug Loop

```
execute_step → ERROR
    ↓
[Capture error details: type, message, traceback, code]
    ↓
[Query experience store for similar error fixes (Section 11.6)]
    ↓
[LLM debug prompt: schema + code + error + similar fixes]
    ↓
[LLM returns: error_analysis, fix_description, corrected_code]
    ↓
execute_step (retry) → SUCCESS or ERROR
    ↓
[Max 3 retries, then report failure to user]
```

### 19.3 Graceful Degradation

- If primary LLM is unavailable → fall back to fast model
- If DuckDB runs out of memory → suggest loading fewer files or smaller samples
- If Excel file is corrupted → report which sheets are readable
- If a source disconnects mid-analysis → report partial results

---

## 20. Testing Strategy

### 20.1 Unit Tests

**Sources:**
- CSV loader: encoding detection, delimiter detection, header detection, edge cases
- Excel structure analyzer: table detection, merged cell handling, formula parsing
- Formula analyzer: parse various formula types, dependency graphs
- CellGrid: serialization, text rendering, cell access
- Database dialects: SQL generation, identifier quoting

**Agent:**
- Classify node: correct mode selection for various questions
- Planning node: valid plan generation for each source type
- Execution node: correct tool dispatch, error handling
- Validation node: correct assessment of result quality

**MCP:**
- Tool registration: all tools discoverable
- Tool input validation: schema enforcement
- Tool output format: correct MCP content types

### 20.2 Integration Tests

- **Database E2E**: Connect → explore schema → ask question → get answer → validate
- **CSV E2E**: Load files → query → cross-file join → visualize
- **Excel E2E**: Load workbook → analyze structure → read formulas → extract table
- **Cross-source**: Load DB + CSV → ask question spanning both → validate
- **MCP server**: Start server → connect client → call tools → verify responses
- **Cost gate**: Load large dataset → trigger cost gate → select strategy → verify optimization

### 20.3 Test Fixtures

Located in `tests/fixtures/`:
- `sample.csv`: Standard CSV with headers (100 rows)
- `no_header.csv`: CSV without header row
- `semicolon.csv`: European-style (semicolon delimiter, comma decimal)
- `multi_table.xlsx`: Workbook with 3 sheets, each with different table structures
- `formulas.xlsx`: Workbook with complex formulas (SUM, VLOOKUP, IF, nested)
- `merged_cells.xlsx`: Workbook with merged header cells and regions
- `non_rectangular.xlsx`: Sheet with scattered data, notes, multiple tables per sheet
- `test.db`: SQLite database with 3 tables (customers, orders, products)

---

## 21. Deployment & Packaging

### 21.1 Entry Points

```toml
# pyproject.toml

[project.scripts]
mcpdb = "mcpdb.__main__:main"           # CLI: mcpdb serve / mcpdb ui
mcpdb-server = "mcpdb.mcp.server:main"  # MCP server only
mcpdb-ui = "mcpdb.ui.app:main"          # UI only
```

### 21.2 CLI Commands

```bash
# Start MCP server (stdio — for Claude Desktop)
mcpdb serve

# Start MCP server (SSE — for web clients)
mcpdb serve --transport sse --port 8765

# Start UI (includes embedded MCP server)
mcpdb ui --port 8080

# Quick connect and query (one-shot)
mcpdb query "postgresql://..." "Show me top 10 customers"

# Load CSV and query
mcpdb csv sales.csv orders.csv --query "Total sales by month"
```

### 21.3 Claude Desktop Integration

```json
// claude_desktop_config.json
{
  "mcpServers": {
    "mcpdb": {
      "command": "mcpdb",
      "args": ["serve"],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

### 21.4 Dependencies

```toml
[project]
name = "mcpdb"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    # Core
    "langgraph>=0.2.0",
    "langchain-core>=0.3.0",
    "mcp>=1.0.0",

    # LLM Providers
    "langchain-anthropic>=0.3.0",
    "langchain-google-genai>=2.0.0",    # Optional
    "langchain-openai>=0.3.0",          # Optional

    # Database
    "sqlalchemy>=2.0.0",
    "psycopg2-binary",
    "pymysql",
    "pyodbc",
    "oracledb",

    # CSV / DuckDB
    "duckdb>=1.0.0",
    "chardet>=5.0.0",

    # Excel
    "openpyxl>=3.1.0",

    # Data & Visualization
    "pandas>=2.0.0",
    "numpy>=1.24.0",
    "matplotlib>=3.8.0",
    "seaborn>=0.13.0",

    # UI
    "nicegui>=2.0.0",

    # Utilities
    "pyyaml>=6.0",
    "pydantic>=2.0.0",
    "python-dotenv>=1.0.0",
    "tabulate>=0.9.0",         # DataFrame to markdown
]

[project.optional-dependencies]
export = [
    "weasyprint>=62.0",        # PDF export
    "nbformat>=5.9.0",         # Jupyter export
    "pygments>=2.17",
]
```

---

## 22. Versioning Roadmap: v0.0.0 → v3.9.9

The spec covers ~4500 lines across 22 sections of interconnected functionality. Building it all at once is unrealistic. Instead, we define a **semantic versioning roadmap** where each version is a working, testable milestone built through incremental coding and refactoring.

**Version semantics:**
- **v0.x** — Pre-release: building blocks, not yet a product
- **v1.x** — First product: single database + MCP + core thinking modes
- **v2.x** — Multi-source: CSV, Excel, cross-source, experience system
- **v3.x** — Advanced: Deep Analysis, production hardening, full vision

**Each patch version (x.y.Z) is one coding session's worth of work** — small enough to build incrementally, big enough to be a testable milestone.

### v0.0.x — Project Bootstrap

**v0.0.1 — Empty project with config**
- `pyproject.toml` with core dependencies (sqlalchemy, mcp, langgraph, pandas)
- `mcpdb/__init__.py`, `mcpdb/__main__.py` (stub)
- Config loading: `mcpdb.yaml` parser with defaults
- Logging setup
- **Test**: `python -m mcpdb` prints version

**v0.0.2 — Data source abstractions**
- `sources/base.py`: `DataSource`, `QueryableSource`, `SpreadsheetSource` ABCs
- `sources/registry.py`: `SourceRegistry` (add/remove/get by ID)
- Type contracts: `SourceMetadata` dataclass
- **Test**: Can instantiate registry, add/remove mock sources

**v0.0.3 — LLM provider interface**
- `llm/provider.py`: `LLMProvider` ABC with `stream()` and `generate()`
- `llm/config.py`: `ModelConfig` dataclass
- Anthropic provider (real implementation with async streaming)
- **Test**: Can stream a simple prompt and collect tokens

### v0.1.x — Database Connectivity

**v0.1.0 — Dialect system**
- `sources/database/dialects/base.py`: `DatabaseDialect` ABC (port from dbtalk)
- `sources/database/dialects/postgresql.py`: First dialect
- `sources/database/dialects/__init__.py`: Dialect factory
- **Test**: `create_dialect("postgresql://...")` returns PostgresDialect

**v0.1.1 — Database connector**
- `sources/database/connector.py`: SQLAlchemy engine, connection pool, retry logic
- Port `retry_on_connection_error` decorator from dbtalk
- `test_connection()`, `execute_query()` → DataFrame
- **Test**: Connect to local SQLite/PostgreSQL, run `SELECT 1`

**v0.1.2 — Schema explorer**
- `sources/database/schema_explorer.py`: Introspect tables, columns, PKs, FKs, indexes
- Row count collection, column statistics
- Table size tags (SMALL/MEDIUM/LARGE/VERY_LARGE)
- **Test**: Connect to test.db, verify schema JSON output

**v0.1.3 — DatabaseSource**
- `sources/database/source.py`: Full `DatabaseSource(QueryableSource)` implementation
- Ties together: connector + schema explorer + dialect
- `get_context_description()` for LLM prompt injection
- **Test**: `DatabaseSource("sqlite:///test.db").execute_query("SELECT * FROM customers")`

**v0.1.4 — Remaining dialects**
- MySQL, SQLite, MSSQL, Oracle dialect implementations
- EXPLAIN prefix/parsing per dialect (`get_explain_prefix()`, `parse_explain_output()`)
- Backend PID query per dialect (`get_backend_pid_query()`)
- **Test**: Each dialect returns correct connect_args, EXPLAIN prefix, system schemas

### v0.2.x — Minimal MCP Server (Tool Mode)

**v0.2.0 — MCP server shell**
- `mcp/server.py`: Server setup with stdio transport
- Tool registration framework
- Capability negotiation
- **Test**: `mcpdb serve` starts, responds to `initialize` handshake

**v0.2.1 — Session tools (4 tools)**
- `connect_database(connection_string)` → connects + introspects
- `list_sources()` → active sources
- `remove_source(source_id)` → disconnect
- `get_source_schema(source_id)` → full schema text
- **Test**: Claude Desktop can connect a DB and see schema

**v0.2.2 — Query tools (3 tools)**
- `execute_sql(source_id, sql, max_rows)` → table result
- `get_table_sample(source_id, table, n)` → first N rows
- `validate_sql(source_id, sql)` → syntax check
- **Test**: Claude Desktop can run SQL queries and see results

**v0.2.3 — Discovery tools (3 tools)**
- `search_schema(source_id, keyword)` → matching tables/columns
- `explain_query(source_id, sql)` → EXPLAIN output
- `render_erd(source_id)` → Mermaid ER diagram
- **Test**: Claude Desktop can explore and understand a database

**v0.2.4 ★ MILESTONE: Tool Mode works**
- End-to-end test: Claude Desktop connects DB → explores schema → runs queries → gets answers
- This is the **first usable product** — Tool Mode only, no agent, client LLM orchestrates everything
- **Tag**: `v0.2.4` — "Tool Mode MVP"

### v0.3.x — Agent Foundation

**v0.3.0 — Agent state & callbacks**
- `agent/state.py`: `AgentState` TypedDict (start with classify + simple fields only)
- `agent/callbacks.py`: `CallbackManager`, `StreamingEvent`
- Event emission infrastructure (not yet connected to MCP transport)
- **Test**: Emit events, verify listeners receive them

**v0.3.1 — Classify node**
- `agent/nodes/classify.py`: Question → mode routing
- Classification prompt template
- Outputs: `query_mode`, `target_sources`, `key_entities`
- **Test**: "What tables exist?" → quick, "Show top customers" → simple

**v0.3.2 — Quick mode**
- `agent/subgraphs/quick.py`: context_answer → validate_answer → END/escalate
- Synthesize from schema context only (no execution)
- **Test**: "How many tables are there?" answered from context

**v0.3.3 — ask_question tool**
- `mcp/tools/analysis.py`: `ask_question(question, source_ids?, mode?)` MCP tool
- Wires MCP → classify → quick subgraph → response
- Streaming events emitted via MCP `notifications/message`
- **Test**: Claude Desktop calls ask_question, gets context-based answer with streaming events

### v0.4.x — Simple Mode (Core Execution Loop)

**v0.4.0 — Plan node**
- `agent/nodes/common.py`: `make_plan_node()` factory
- Planning prompt: question + schema → JSON plan with steps
- **Test**: Question → plan with 1-3 SQL/Python steps

**v0.4.1 — Execute node (SQL only)**
- Execute node: dispatches `sql` action type → `DatabaseSource.execute_query()`
- Result → DataFrame → artifact
- Step tracking: time_ms, result_preview
- **Test**: Plan with SQL step → executed → artifact created

**v0.4.2 — Debug node**
- `make_debug_node()`: error + original code → LLM fix → retry
- Max 3 retries per step
- **Test**: Deliberately broken SQL → auto-fixed → succeeds

**v0.4.3 — Synthesize node**
- `make_synthesize_node()`: all step results → final markdown response
- Uses fast LLM for speed
- **Test**: Step results → coherent natural language answer

**v0.4.4 — Simple subgraph wired**
- `agent/subgraphs/simple.py`: plan → execute ⟷ debug → synthesize
- Full loop: question → plan → execute → answer
- **Test**: "Show top 10 customers by revenue" → SQL → table → answer

**v0.4.5 — Validate + replan**
- `agent/nodes/validators.py`: validate_result, replan
- Max 1 replan in Simple mode
- **Test**: Question where first plan misses the point → replan → correct answer

**v0.4.6 ★ MILESTONE: Agent Mode works**
- ask_question with Simple mode produces correct answers from databases
- Streaming events show classify → plan → execute → synthesize
- **Tag**: `v0.4.6` — "Agent Mode MVP"

### v0.5.x — Python Sandbox

**v0.5.0 — Basic subprocess sandbox**
- `sandbox/executor.py`: Execute Python code in subprocess
- Capture stdout, stderr, return values
- Timeout via signal.alarm
- **Test**: `execute_python("print(1+1)")` → "2"

**v0.5.1 — Security hardening**
- `sandbox/security.py`: RestrictedPython compilation
- Import allowlist (pandas, numpy, matplotlib, seaborn, json, re, math, datetime)
- Resource limits (RLIMIT_AS, RLIMIT_CPU, RLIMIT_NOFILE=0)
- **Test**: `import os` → blocked, `import subprocess` → blocked

**v0.5.2 — DataFrame & chart capture**
- Pre-inject `df` (last query result), `pd`, `np`, `plt`, `sns`
- Capture matplotlib figures as base64 PNG
- Capture DataFrame results
- **Test**: `plt.bar(df['name'], df['value'])` → chart artifact

**v0.5.3 — Integrate into execute node**
- Execute node dispatches `python` action type → sandbox
- Artifacts (charts, tables) captured and stored
- **Test**: Plan with SQL step + Python visualization step → table + chart

### v0.6.x — Streaming & Cancellation

**v0.6.0 — LLM token streaming**
- All LLM calls use `stream()` via `stream_llm_call()` wrapper
- Emit `llm/start`, `llm/token`, `llm/complete` events
- Cancellation check between token chunks
- **Test**: Planning call → see tokens streaming in real-time

**v0.6.1 — Full event emission**
- Every agent node emits its events (classify/start, plan/ready, step/start, etc.)
- MCP notification handler: events → `notifications/message` JSON-RPC
- **Test**: Full ask_question flow → all 10+ events emitted in order

**v0.6.2 — CancellationToken**
- `agent/cancellation.py`: Thread-safe token, CancelledException
- `cancel_execution` MCP tool
- Check at natural pause points (before each step, before each LLM call)
- Partial result synthesis on cancellation
- **Test**: Start long query → cancel → get partial results

**v0.6.3 — In-flight SQL cancellation**
- `sources/database/query_runner.py`: `CancellableQueryRunner`
- Backend PID tracking, dialect-specific kill commands
- `asyncio.wait(FIRST_COMPLETED)` pattern
- **Test**: Start slow query → cancel → query killed at DB level

**v0.6.4 — Mid-execution user input**
- `agent/user_input_queue.py`: `UserInputQueue`
- `add_context` MCP tool
- Pre-step injection: check queue before each step
- **Test**: Start analysis → add context mid-execution → plan revised

### v1.0.0 ★ FIRST RELEASE — Single DB + MCP + Quick/Simple

**What works**: Connect any of 5 database types, ask natural language questions, get SQL + Python + charts, stream thinking steps, cancel mid-execution, add context. Tool Mode and Agent Mode both functional.

**Tools available**: ~15 (session: 4, discovery: 3, querying: 3, analysis: 2, control: 3)
**Modes**: Quick + Simple (2 of 5)

### v1.1.x — Cost Awareness & EXPLAIN

**v1.1.0 — Cost check node (fast-path)**
- Layer 0: Regex scan for LIMIT/TABLESAMPLE patterns
- Layer 3: Heuristic fallback (table sizes + query patterns)
- Routing: not_required → execute, recommended/necessary → strategy_gate
- **Test**: Simple query → skips cost gate; full scan on 5M rows → flagged

**v1.1.1 — EXPLAIN integration**
- Layer 1: Run EXPLAIN on each SQL step
- `ExplainResult` dataclass (estimated_rows, scan_type, join_types, warnings)
- **Test**: EXPLAIN on index scan → low cost; EXPLAIN on seq scan → flagged

**v1.1.2 — LLM cost check**
- Layer 2: Send EXPLAIN output + table sizes to reasoning LLM
- Cost analysis JSON output
- **Test**: LLM correctly identifies expensive nested loop join

**v1.1.3 — Strategy gate state machine**
- Strategy gate: save AgentState to `pending_strategies[session_id]`
- Emit `strategy_request` event, return `{status: "awaiting_strategy"}`
- 10-minute TTL, one pending per session
- **Test**: Expensive query → strategy_request emitted → state saved

**v1.1.4 — submit_strategy tool**
- `submit_strategy(session_id, strategy)`: restore state, set strategy_choice, re-invoke
- Error cases: not found, expired, cancelled
- **Test**: Full round-trip: ask → cost gate → submit_strategy → execution resumes

**v1.1.5 — LLM cost tracking**
- `LLMUsage` dataclass: tokens_in, tokens_out, estimated_cost_usd
- Budget enforcement: `budget_per_question_usd` config
- Cost included in `llm/complete` events
- **Test**: Deep analysis burns $0.50 → tracked; budget exceeded → graceful stop

### v1.2.x — Optimization Mode

**v1.2.0 — optimize_plan node**
- SAMPLE strategy: rewrite SQL with dialect-specific sampling
- FULL strategy: keep original (chunked execution if needed)
- CANCEL strategy: emit cancellation, route to END
- **Test**: SAMPLE rewrites `SELECT * FROM orders` → `SELECT * FROM orders TABLESAMPLE SYSTEM(5)`

**v1.2.1 — Optimization subgraph**
- `agent/subgraphs/optimization.py`: plan → cost_check → strategy_gate → optimize_plan → execute → synthesize
- Two-phase execution wired end-to-end
- **Test**: "Average order value" on 10M row table → cost gate → SAMPLE → approximate answer

### v1.3.x — Extended Mode

**v1.3.0 — Checkpoint + revise nodes**
- Checkpoint: every N steps, LLM reviews progress → continue/revise/done
- Revise plan: rewrite remaining steps based on checkpoint feedback
- **Test**: 5-step plan → checkpoint after step 3 → revise remaining steps

**v1.3.1 — Reflect node**
- After all steps: LLM reflects on what was learned
- Reflection injected into synthesis prompt for richer answers
- **Test**: Extended analysis → reflection captures unexpected pattern

**v1.3.2 — Extended subgraph**
- `agent/subgraphs/extended.py`: Full topology with checkpoints + reflection
- Extended-specific streaming events (checkpoint/start, revise/ready, reflect/ready)
- **Test**: "Comprehensive analysis of customer churn" → 6 steps with checkpoint → rich report

**v1.3.3 ★ MILESTONE: All 4 core modes**
- Quick, Simple, Optimization, Extended all working
- Classifier routes to correct mode based on question complexity
- **Tag**: `v1.3.3` — "Four Modes"

### v1.4.x — Discovery & Conversation Tools

**v1.4.0 — Profile tools**
- `profile_table(source_id, table)`: row count, column stats, nulls, distinct values
- `profile_column(source_id, table, column)`: histogram, top values, patterns
- **Test**: Profile produces meaningful statistical summary

**v1.4.1 — Relationship tools**
- `find_relationships(source_id)`: detect FKs + inferred joins
- `suggest_joins(source_id, tables)`: suggest join conditions
- **Test**: Detects customers → orders FK relationship

**v1.4.2 — MCP resources**
- `schema://{source_id}` → full schema JSON
- `erd://{source_id}` → Mermaid diagram
- `session://sources` → all active sources
- `session://execution_status` → current agent state
- **Test**: Claude Desktop reads resources for context

**v1.4.3 — Follow-up generation**
- `suggest_followups(session_id)`: context-aware follow-up questions
- Recommendation engine based on schema + last results
- **Test**: After "top customers" query → suggests "revenue trend", "segment analysis"

**v1.4.4 — MCP prompts**
- `explore_source`: guided multi-step exploration workflow
- `deep_table_analysis`: in-depth table analysis prompt
- **Test**: Claude Desktop uses explore_source prompt to discover database

### v1.5.x — Session & History Polish

**v1.5.0 — Session lifecycle**
- Session ID format, TTL, cleanup on disconnect
- Max concurrent sessions
- `get_session_status` tool
- **Test**: Connect → disconnect → reconnect → session cleaned up

**v1.5.1 — Conversation history**
- Sliding window: last 50 messages in full
- Older messages summarized by fast LLM
- Summary created when window exceeded
- **Test**: 60-message conversation → messages 1-10 summarized → context preserved

**v1.5.2 ★ MILESTONE: Complete single-DB product**
- All modes, all discovery tools, streaming, cancellation, cost gate, history
- **Tag**: `v1.5.2` — "Database Product Complete"

### v2.0.x — CSV Support

**v2.0.0 — DuckDB backend**
- `sources/csv/duckdb_backend.py`: DuckDB session management
- Table registration from DataFrames
- Memory limit enforcement
- **Test**: Register DataFrame in DuckDB, query with SQL

**v2.0.1 — CSV loader**
- `sources/csv/loader.py`: encoding detection (chardet), delimiter detection, header detection
- Multi-file loading with unique table names
- **Test**: Load `sales.csv` with semicolons + European decimals → correct DataFrame

**v2.0.2 — CsvSource**
- `sources/csv/source.py`: `CsvSource(QueryableSource)` implementation
- Full SQL query capability via DuckDB
- `load_csv_files` MCP tool
- **Test**: Load CSV → ask_question → SQL generated → correct answer

**v2.0.3 — Multi-file CSV sessions**
- Load multiple CSVs into same DuckDB session
- Cross-file joins via SQL
- **Test**: Load sales.csv + products.csv → "join sales with products" → works

### v2.1.x — Cross-Source Federation

**v2.1.0 — SessionManager routing**
- Detect when query spans multiple sources
- Source capability matrix
- **Test**: Classify "join CSV sales with DB customers" → requires_cross_source = true

**v2.1.1 — Strategy 1: DuckDB native attachment**
- PostgreSQL: postgres_scanner extension
- MySQL: mysql_scanner extension
- SQLite: direct DuckDB attachment
- **Test**: PostgreSQL table + CSV → joined in DuckDB without data transfer

**v2.1.2 — Strategy 2: Pushdown + transfer**
- Execute subquery on remote DB → transfer result → load into DuckDB → join
- Memory guard: estimate transfer size from row count × avg_row_width
- **Test**: MySQL subquery → 10K rows transferred → joined with CSV in DuckDB

**v2.1.3 — cross_source_query tool**
- `cross_source_query(sql, source_ids)` MCP tool
- Automatic strategy selection based on source types
- **Test**: End-to-end cross-source query from Claude Desktop

### v2.2.x — Excel Support

**v2.2.0 — Core data structures**
- `sources/excel/cell_grid.py`: CellValue, CellGrid, MergedRegion
- Text rendering: `CellGrid.to_text()` for LLM consumption
- **Test**: Build CellGrid from mock data → text rendering looks correct

**v2.2.1 — Workbook reader**
- `sources/excel/workbook_reader.py`: openpyxl dual-mode (formulas + values)
- Read ranges, list sheets, detect merged regions
- **Test**: Read real xlsx file → correct values and formulas extracted

**v2.2.2 — Structure analyzer (two-case)**
- `sources/excel/structure_analyzer.py`: Classify regions as Case 1 (table) or Case 2 (text)
- Conservative: if in doubt → Case 2 (text)
- DetectedTable, TextRegion output
- **Test**: Dashboard xlsx → header region as text, data table as DetectedTable

**v2.2.3 — Table extractor + DuckDB**
- Case 1 tables → DataFrame → DuckDB (same as CSV path)
- Named as `{workbook}_{sheet}_{range}`
- SQL queryable
- **Test**: Extract table from xlsx → query with SQL → correct results

**v2.2.4 — ExcelSource + MCP tools**
- `ExcelSource(SpreadsheetSource)` implementation
- MCP tools: `load_excel`, `list_sheets`, `read_range`, `extract_excel_table`, `explain_formula`
- **Test**: Claude Desktop loads xlsx → explores structure → queries extracted table

**v2.2.5 — Formula support (basic)**
- `FormulaAnalyzer`: parse formula, explain in natural language (via LLM)
- List all formulas in range
- **Test**: `=SUM(A1:A10)` → "Sums values in cells A1 through A10"

### v2.3.x — Experience System (Basic)

**v2.3.0 — Source fingerprinting + storage**
- `experience/fingerprint.py`: Stable identity hash per source
- `experience/store.py`: JSONL-based per-source storage
- `experience/records.py`: SuccessRecord, CodeStep
- **Test**: Two queries → two records stored → retrievable by fingerprint

**v2.3.1 — Exact-match cache**
- `experience/cache.py`: intent_hash → cached response (O(1) lookup)
- Schema drift detection (invalidate on schema change)
- **Test**: Ask same question twice → second time returns cached response (no LLM call)

**v2.3.2 — Integrate into agent**
- Classify node checks cache before routing
- ExperienceRecorder auto-records on synthesis success
- **Test**: ask_question → LLM answer → cached → ask again → instant response

**v2.3.3 ★ MILESTONE: Multi-source product**
- Databases (5 dialects) + CSV + Excel + cross-source
- Experience caching for instant repeat queries
- **Tag**: `v2.3.3` — "Multi-Source Product"

### v2.4.x — Experience Templates (Semantic)

**v2.4.0 — Embedding service**
- `experience/embeddings.py`: Provider-agnostic embedding
- Anthropic embeddings as default, Jaccard word-overlap as fallback
- **Test**: Embed two similar questions → cosine similarity > 0.8

**v2.4.1 — Template retrieval**
- `experience/retriever.py`: Semantic search with table-overlap boosting
- Threshold-based injection: high (>0.85) → template, medium (>0.65) → hint
- **Test**: "Top 10 customers by revenue" cached → "Top 5 customers by orders" uses as template

**v2.4.2 — Planning integration**
- Template injected into planning prompt as "Here's a similar successful approach"
- Debug node retrieves error-fix pairs for similar errors
- **Test**: Template-assisted plan has fewer execution errors than cold plan

**v2.4.3 — Anti-pattern tracking**
- FailureRecord tracking
- Anti-patterns injected into planning prompt: "Avoid: ... (failed N times)"
- Min 2 occurrences before promotion
- **Test**: Same error twice → anti-pattern injected → LLM avoids it

### v2.5.x — Frontend UI (Basic)

**v2.5.0 — App scaffolding**
- `ui/app.py`: NiceGUI application with routing
- `ui/theme.py`: Color scheme, typography
- Basic layout: sidebar + main content
- **Test**: `mcpdb ui` → browser opens → empty app renders

**v2.5.1 — Chat page**
- `ui/pages/chat.py`: Message list + input field
- Markdown rendering for responses
- **Test**: Type question → response appears with formatting

**v2.5.2 — Source panel**
- `ui/components/source_panel.py`: Connection forms for DB/CSV/Excel
- Sidebar with active sources
- **Test**: Connect database via UI form → schema visible in sidebar

**v2.5.3 — Streaming + artifacts**
- `ui/streaming.py`: WebSocket connection for real-time events
- `ui/components/artifact_viewer.py`: Tables (DataFrames) and charts (PNG)
- Thinking panel with typewriter effect for LLM tokens
- **Test**: Ask question → see thinking → see table/chart → see answer

**v2.5.4 — Execution monitor**
- `ui/components/execution_monitor.py`: Step-by-step progress with timing
- Phase indicator (Classify → Plan → Execute → Synthesize)
- Cancel button
- **Test**: Multi-step query → progress bar → cancel mid-execution → partial results

### v3.0.x — Deep Analysis

**v3.0.0 — Blueprint creation**
- `agent/deep_analysis.py`: `create_blueprint` node
- LLM generates research goal + 3-7 investigation questions
- **Test**: "Investigate customer churn patterns" → blueprint with 5 investigations

**v3.0.1 — Investigation orchestration**
- Each investigation invokes the full agent graph (Simple/Extended mode)
- Results collected per investigation
- **Test**: Investigation "What is the churn rate by segment?" → runs Simple mode → results stored

**v3.0.2 — Reasoning loop**
- `reason_about_results`: LLM reviews completed investigations
- Adaptive: skip redundant investigations, add new ones based on discoveries
- Max 10 iterations, cost tracking per investigation
- **Test**: After 3 investigations, reasoning skips redundant one, adds new angle

**v3.0.3 — Deep synthesis**
- Combine all investigation results into comprehensive research report
- Include methodology, findings, limitations, recommendations
- **Test**: 5 investigations → structured report with cross-referenced findings

**v3.0.4 — Deep Analysis streaming**
- Events: `deep/blueprint`, `deep/investigation_start`, `deep/investigation_complete`, `deep/reasoning`, `deep/synthesis_start`
- **Test**: Full deep analysis → client sees investigation progress in real-time

### v3.1.x — Frontend Advanced

**v3.1.0 — Schema viewer**
- `ui/components/schema_viewer.py`: Tree view of tables/columns/types
- Click to see sample data
- **Test**: Expand table → see columns → click → sample rows appear

**v3.1.1 — Excel viewer**
- `ui/components/excel_viewer.py`: Cell grid rendering (Case 2 regions)
- Formula display toggle
- **Test**: Load Excel → see cell grid with formulas highlighted

**v3.1.2 — Cost gate dialog**
- `ui/components/cost_gate_dialog.py`: Strategy selection buttons
- Cost explanation display
- **Test**: Expensive query → dialog appears → select SAMPLE → execution continues

**v3.1.3 — Deep Analysis UI**
- Investigation progress tracker
- Expandable findings per investigation
- Research report rendering
- **Test**: Deep analysis → see investigations completing one by one

### v3.2.x — Export

**v3.2.0** — Export to PDF (weasyprint)
**v3.2.1** — Export to HTML
**v3.2.2** — Export to Jupyter notebook (nbformat)
**v3.2.3** — Export dialog in UI + `export_conversation` MCP tool

### v3.3.x — Experience Advanced

**v3.3.0 — Strategy records**
- Remember which optimization strategies worked for which query patterns
- Inject into cost check: "Last time, SAMPLE with 5% worked well for this pattern"
- **Test**: SAMPLE strategy → recorded → similar query → SAMPLE auto-suggested

**v3.3.1 — Cross-dialect knowledge transfer**
- Dialect-level patterns shared across all sources of same type
- Promotion threshold: 2+ sources confirm pattern
- **Test**: PostgreSQL pattern "always quote mixed-case identifiers" promoted

**v3.3.2 — Schema drift detection**
- On reconnection: compare current schema hash to stored hash
- If changed: invalidate affected cache entries, log warning
- **Test**: Add column to table → cache for affected queries invalidated

**v3.3.3 — Experience MCP tools**
- `get_experience_stats`, `vote_response`, `clear_experience`, `list_cached_queries`, `invalidate_cache_entry`
- **Test**: View stats → vote down bad response → cache cleared

### v3.4.x — Excel Advanced

**v3.4.0 — Formula dependency graph**
- `get_dependencies(sheet, cell)` → list of upstream cells
- Visualize as directed graph
- **Test**: Cell with `=SUM(A1:A10)` → depends on A1 through A10

**v3.4.1 — Formula cluster analysis**
- Detect groups of similar formulas (e.g., column of SUMs)
- Explain formula patterns
- **Test**: Column C all `=A*B` → "Column C multiplies A by B for each row"

**v3.4.2 — Multi-workbook support**
- Load multiple xlsx files in one session
- Cross-workbook references: `budget::Sheet1!A1`
- **Test**: Load budget.xlsx + actuals.xlsx → "compare budget vs actuals" → works

### v3.5.x — Security Hardening

**v3.5.0** — Sandbox audit: seccomp profile (Linux) / sandbox-exec (macOS), block network syscalls, verify RestrictedPython blocks all known escape vectors
**v3.5.1** — Credential handling: password redaction after engine creation, MCP log masking, no credential disk persistence
**v3.5.2** — SQL injection prevention: read-only mode enforcement, parameterized catalog queries, `_sanitize_identifier()` on all user-provided names
**v3.5.3** — Rate limiting + circuit breakers: max concurrent queries per session, LLM call circuit breaker, DuckDB memory limit enforcement

### v3.6.x — Multi-Provider LLM

**v3.6.0** — Google Gemini provider
**v3.6.1** — OpenAI provider
**v3.6.2** — Local model support (Ollama)
**v3.6.3** — Provider fallback chain (primary → secondary → fast)

### v3.7.x — Progressive Tool Disclosure

**v3.7.0** — Tool visibility tiers (5 tiers)
**v3.7.1** — Dynamic tools/list based on session state
**v3.7.2** — Tool usage analytics

### v3.8.x — Session Persistence

**v3.8.0** — Session persistence to disk (reconnect after server restart)
**v3.8.1** — Multi-session support (concurrent users)
**v3.8.2** — Session export/import

### v3.9.x — Release Polish

**v3.9.0 — CLI entry points**
- `mcpdb serve` (stdio for Claude Desktop)
- `mcpdb serve --transport sse --port 8765` (web clients)
- `mcpdb ui --port 8080` (full UI)
- `mcpdb query "postgresql://..." "question"` (one-shot)

**v3.9.1** — Documentation: README with quickstart, API docs for all MCP tools, example notebooks
**v3.9.2** — CI/CD: GitHub Actions (lint + test + build), release automation
**v3.9.3** — Packaging: `pip install mcpdb`, optional dependency groups (`mcpdb[excel]`, `mcpdb[export]`, `mcpdb[oracle]`)

**v3.9.9 ★ FINAL RELEASE**
- Full spec implemented
- All 5 modes, all 3 source types, 44 tools, experience system, UI, export
- **Tag**: `v3.9.9` — "MCPDB 1.0 Complete"

### Milestone Summary

| Version | Codename | What Works |
|---------|----------|------------|
| v0.2.4 | Tool Mode MVP | Claude Desktop connects DB, runs SQL, sees schema |
| v0.4.6 | Agent Mode MVP | ask_question → Quick/Simple → correct answers |
| v1.0.0 | First Release | Single DB + streaming + cancellation + Quick/Simple |
| v1.3.3 | Four Modes | Quick + Simple + Optimization + Extended all working |
| v1.5.2 | DB Product Complete | All modes + discovery + cost gate + history |
| v2.3.3 | Multi-Source Product | DB + CSV + Excel + cross-source + caching |
| v2.5.4 | UI Usable | Full frontend with streaming + artifacts |
| v3.0.4 | Deep Analysis | All 5 thinking modes operational |
| v3.9.9 | Full Vision | Complete spec implemented |

### Verification

Each version tag should:
1. Pass all existing tests
2. Have at least one new integration test for the feature added
3. Be demonstrable (either via CLI, MCP client, or UI depending on stage)

---

## Appendix A: Prompt Templates

### A.1 Classification Prompt (Multi-Source)

```
You are a query classifier for a multi-source data assistant.

ACTIVE DATA SOURCES:
{sources_summary}

Each source has these details:
{source_details}

CONVERSATION CONTEXT:
{conversation_context}

USER QUESTION: {question}

AVAILABLE MODES:
1. **quick** — Answer from known context (schema questions, previous results)
2. **simple** — 1-5 execution steps (DEFAULT for most data questions)
3. **extended** — 3-10 steps for comprehensive analysis, EDA, root cause
4. **optimization_required** — Large table operations (>1M rows, no narrow filters)

Also determine:
- **target_sources**: Which data sources are needed to answer this question
- **requires_cross_source**: Does the answer need data from multiple sources?
- **is_excel_structure_query**: Is this asking about Excel layout/formulas (not data values)?

Respond with JSON:
{{
    "mode": "quick|simple|extended|optimization_required",
    "reasoning": "Why this mode",
    "target_sources": ["source_id_1"],
    "requires_cross_source": false,
    "is_excel_structure_query": false,
    "key_entities": ["tables/columns/sheets mentioned"]
}}
```

### A.2 Planning Prompt (Multi-Source)

```
You are a data analysis planner. Create an execution plan for the user's question.

ACTIVE DATA SOURCES:
{sources_context}

USER QUESTION: {question}
EXECUTION MODE: {mode}
{mode_guidance}

AVAILABLE ACTIONS:
- "sql": Execute SQL on a database or CSV source (specify source_id)
- "python": Execute Python code (pandas, matplotlib, seaborn available)
- "excel_read": Read cells from an Excel sheet (returns CellGrid with formulas)
- "excel_structure": Analyze Excel sheet layout and detect tables
- "excel_formula": Explain a formula and its dependencies
- "excel_extract": Extract a rectangular table from Excel as DataFrame
- "cross_query": Query across multiple sources (data joined in DuckDB)
- "schema": Get schema/structure details
- "sample": Get sample rows from a table

CRITICAL RULES:
- For SQL steps: include the actual SQL code
- For Python steps: `df` contains the last SQL/extraction result
- For Excel: use excel_read for non-rectangular data; excel_extract only for confirmed tables
- For cross-source: specify which source provides which table
- Always use exact column/table names from the source schemas

{sql_syntax_rules}

Respond with JSON:
{{
    "analysis": "What the user wants",
    "approach": "How we'll get it",
    "target_sources": ["source_id_1"],
    "requires_cross_source": false,
    "steps": [
        {{
            "step_number": 1,
            "action": "sql|python|excel_read|...",
            "source_id": "source_id_1",
            "description": "What this step does",
            "code": "SQL/Python code or operation parameters"
        }}
    ]
}}
```

### A.3 System Prompt (Multi-Source)

```
You are a helpful data assistant that helps users explore and analyze data from multiple sources.

ACTIVE DATA SOURCES:
{sources_context}

AVAILABLE TOOLS:
1. **execute_sql**: SQL queries on databases and CSV files
2. **execute_python**: Python analysis with pandas, matplotlib, seaborn
3. **read_excel_range**: Read Excel cells (values and/or formulas)
4. **analyze_sheet_structure**: Detect tables and layout in Excel
5. **explain_formula**: Explain what an Excel formula computes
6. **extract_excel_table**: Extract rectangular table from Excel
7. **cross_source_query**: Query across multiple data sources

GUIDELINES:
{guidelines}

EXCEL-SPECIFIC GUIDELINES:
- Excel data is NOT always tabular — use analyze_sheet_structure first
- Formulas carry semantic meaning — use explain_formula to understand calculations
- Merged cells need special attention — check SheetStructure.merged_regions
- Multi-sheet workbooks may have different structures per sheet
- When the user asks about Excel data, determine if they need:
  a) The computed values (what Excel displays)
  b) The formulas (how values are calculated)
  c) The structure (how the spreadsheet is organized)
- Use excel_extract ONLY for confirmed rectangular regions
- Use read_excel_range for everything else

CSV-SPECIFIC GUIDELINES:
- CSV files are loaded as SQL tables in DuckDB
- Use standard SQL (PostgreSQL-compatible) for CSV queries
- Multiple CSV files can be JOINed using standard SQL
- Table names are derived from filenames (e.g., "sales_2024")

CROSS-SOURCE GUIDELINES:
- When data from multiple sources is needed, use cross_source_query
- Specify which source provides which table
- The system will fetch data and join in DuckDB
```

### A.4 Debug Prompt

```
The following code failed. Analyze and fix it.

SOURCE: {source_type} ({source_id})
{source_specific_context}

ORIGINAL CODE ({code_type}):
```
{original_code}
```

ERROR:
{error_message}

ATTEMPT: {attempt} of {max_attempts}

{similar_fixes}

Respond with JSON:
{{
    "error_analysis": "What went wrong",
    "fix_description": "What's being fixed",
    "corrected_code": "Fixed code"
}}
```

---

## Appendix B: MCP Tool Schemas

### B.1 connect_database

```json
{
    "name": "connect_database",
    "description": "Connect to a SQL database. Supports PostgreSQL, MySQL, SQLite, SQL Server, Oracle.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "connection_string": {
                "type": "string",
                "description": "SQLAlchemy connection string (e.g., postgresql://user:pass@host:5432/db)"
            },
            "display_name": {
                "type": "string",
                "description": "Human-readable name for this connection (optional)"
            }
        },
        "required": ["connection_string"]
    }
}
```

### B.2 load_csv_files

```json
{
    "name": "load_csv_files",
    "description": "Load one or more CSV files for SQL querying. Each file becomes a named table.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "file_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Paths to CSV files"
            },
            "options": {
                "type": "object",
                "properties": {
                    "encoding": {"type": "string", "description": "Force encoding (auto-detect if omitted)"},
                    "delimiter": {"type": "string", "description": "Force delimiter (auto-detect if omitted)"},
                    "has_header": {"type": "boolean", "description": "Force header presence (auto-detect if omitted)"}
                }
            }
        },
        "required": ["file_paths"]
    }
}
```

### B.3 load_excel_file

```json
{
    "name": "load_excel_file",
    "description": "Load an Excel workbook (.xlsx, .xlsm, .xls) for exploration. Supports formulas, merged cells, multi-sheet.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to Excel file"
            }
        },
        "required": ["file_path"]
    }
}
```

### B.4 read_excel_range

```json
{
    "name": "read_excel_range",
    "description": "Read cells from an Excel sheet. Returns cell values, formulas, and merge info.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "source_id": {"type": "string"},
            "sheet": {"type": "string", "description": "Sheet name"},
            "range": {"type": "string", "description": "Cell range (e.g., 'A1:D10'). Omit for entire sheet."},
            "include_formulas": {"type": "boolean", "default": false}
        },
        "required": ["source_id", "sheet"]
    }
}
```

### B.5 analyze_sheet_structure

```json
{
    "name": "analyze_sheet_structure",
    "description": "Analyze the layout of an Excel sheet: detect tables, headers, merged cells, formulas.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "source_id": {"type": "string"},
            "sheet": {"type": "string"}
        },
        "required": ["source_id", "sheet"]
    }
}
```

### B.6 ask_question

```json
{
    "name": "ask_question",
    "description": "Ask a natural language question about your data. The agent will plan, execute queries, and synthesize a response.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Your question about the data"},
            "mode": {"type": "string", "enum": ["auto", "quick", "simple", "extended", "deep"], "default": "auto", "description": "Thinking mode override (auto = let classifier decide)"},
            "deep_analysis": {"type": "boolean", "default": false, "description": "Shorthand: if true, sets mode=deep"}
        },
        "required": ["question"]
    }
}
```

---

## Appendix C: Reference Architecture from dbtalk

The following components from dbtalk are ported with minimal changes:

| dbtalk Component | MCPDB Location | Changes |
|-----------------|----------------|---------|
| `core/database.py` | `sources/database/connector.py` | Unchanged core logic |
| `core/dialects/*` | `sources/database/dialects/*` | Unchanged |
| `core/schema_explorer.py` | `sources/database/schema_explorer.py` | Unchanged |
| `core/query_optimizer.py` | `sources/database/query_optimizer.py` | Unchanged |
| `core/query_cost_estimator.py` | `sources/database/cost_estimator.py` | Unchanged |
| `agent/state.py` | `agent/state.py` | Extended with multi-source fields |
| `agent/graph.py` | `agent/graph.py` | Uses SessionManager instead of direct connector |
| `agent/prompts.py` | `agent/prompts.py` | Extended with multi-source + Excel prompts |
| `agent/tools.py` | `mcp/tools.py` | Refactored as MCP tools |
| `agent/callbacks.py` | `agent/callbacks.py` | Extended with MCP notifications |
| `agent/nodes/*` | `agent/nodes/*` | Extended with source-aware dispatch |
| `agent/subgraphs/*` | `agent/subgraphs/*` | Minimal changes |
| `agent/deep_analysis.py` | `agent/deep_analysis.py` | Ported as Mode 5 meta-loop |
| `agent/rag_retriever.py` | `experience/*` | Completely redesigned as per-source experience system (Section 11) |
| `agent/recommendations.py` | `agent/recommendations.py` | Multi-source recommendations |
| `core/shared_state.py` | Removed | Replaced by SessionManager |
| `ui/*` (Streamlit) | `ui/*` (NiceGUI) | Complete rewrite |
| `app.py` (Streamlit) | `ui/pages/chat.py` | Complete rewrite |

### Components NOT ported (new):
- `sources/base.py` — new abstraction layer
- `sources/csv/*` — entirely new
- `sources/excel/*` — entirely new
- `experience/*` — entirely new per-source learning system (replaces simple RAG)
- `mcp/*` — entirely new
- `llm/*` — new provider abstraction
- `sandbox/*` — extracted from tools.py, hardened
- `session.py` — new multi-source orchestration

---

*End of Technical Specification*
