"""MCPDB CLI entry point."""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

# Suppress noisy third-party warnings
warnings.filterwarnings("ignore", message=".*urllib3.*")
warnings.filterwarnings("ignore", message=".*chardet.*")
warnings.filterwarnings("ignore", message=".*google.generativeai.*")

from mcpdb import __version__
from mcpdb.config import load_config
from mcpdb.logging import setup_logging


USAGE = f"""\
mcpdb v{__version__} — MCP server for natural language database exploration

Usage:
  mcpdb                          Print version
  mcpdb serve                    Start MCP server (stdio, for MCP clients)
  mcpdb serve --transport sse    Start MCP server (SSE, for web clients)
  mcpdb serve --port 8765        Start SSE server on custom port
  mcpdb web                      Start web client (recommended)
  mcpdb web --port 8080          Web client on custom port
  mcpdb web --no-browser         Start without opening browser
  mcpdb web --no-cache           Skip cache lookup, still populate
  mcpdb query <conn> <question>  One-shot query mode
  mcpdb query file.csv <question>  Query CSV file(s) (comma-separated)
  mcpdb query file.xlsx <question> Query Excel workbook
  mcpdb query <conn> <question> --no-cache  Skip cache, still populate
  mcpdb repl <conn>              Interactive REPL mode
  mcpdb repl file.csv            REPL with CSV source
  mcpdb repl file.xlsx           REPL with Excel source
  mcpdb repl <conn> --no-cache   REPL without cache lookup
  mcpdb tui <conn>               Textual TUI mode (windowed)
  mcpdb tui <conn> --no-cache    TUI without cache lookup
  mcpdb clean_cache              Clear all experience cache data
  mcpdb clean_cache --source <fp>  Clear cache for one source
  mcpdb clean_cache --stats      Show cache stats without clearing
  mcpdb experience eval          Evaluate pending staged results
  mcpdb experience stats         Show cache & staging statistics
  mcpdb experience clear [--all] Clear all experience data
  mcpdb experience clear --source <fp>  Clear one source fingerprint
  mcpdb experience export [--source <fp>]  Export experience data as JSON
  mcpdb experience antipatterns [--source <fp>]  List anti-patterns
"""

MANUAL = f"""\
{'=' * 72}
  MCPDB v{__version__} — Natural Language Database Explorer
{'=' * 72}

  Ask questions about your data in plain English. MCPDB translates them
  into SQL, executes safely, and returns formatted answers with charts.

  Works with PostgreSQL, MySQL, SQLite, SQL Server, Oracle, CSV, and
  Excel files. Runs standalone via web UI, REPL, TUI, one-shot CLI,
  or as an MCP server for any MCP-compatible client.

{'─' * 72}
  QUICK START
{'─' * 72}

  Web client (recommended):
    mcpdb web

  One-shot query:
    mcpdb query "postgresql://user:pass@host/db" "How many orders last month?"
    mcpdb query sales.csv "What is the top product by revenue?"
    mcpdb query report.xlsx "Summarize sheet 1"

  Interactive REPL:
    mcpdb repl "mysql+pymysql://user:pass@host/db"

  MCP server (for any MCP-compatible client):
    mcpdb serve

{'─' * 72}
  COMMANDS
{'─' * 72}

  mcpdb                               Print version
  mcpdb web [OPTIONS]                  Start web client (browser UI)
  mcpdb query <source> <question>      One-shot query
  mcpdb repl <source>                  Interactive REPL
  mcpdb tui <source>                   Textual TUI (windowed terminal UI)
  mcpdb serve [OPTIONS]                Start MCP server
  mcpdb experience <subcommand>        Manage experience cache
  mcpdb clean_cache [OPTIONS]          Clear cached data
  mcpdb help                           This manual
  mcpdb --version                      Print version

  <source> can be:
    - Database URL:  postgresql://user:pass@host/db
                     mysql+pymysql://user:pass@host/db
                     sqlite:///path/to/file.db
    - CSV file(s):   data.csv  or  a.csv,b.csv,c.csv
    - Excel file:    report.xlsx

{'─' * 72}
  WEB CLIENT — mcpdb web
{'─' * 72}

  Full-featured browser UI with real-time query execution.

  Options:
    --port PORT       Custom port (default: auto-detect free port)
    --no-browser      Start server without opening browser
    --no-cache        Skip experience cache lookup

  Features:
    - Connect databases, upload CSV/Excel from the browser
    - Real-time execution monitor: phase pipeline, plan steps, progress
    - Charts rendered inline (matplotlib/seaborn captured automatically)
    - Follow-up question suggestions after every response
    - Export results to HTML report, PDF, or Jupyter notebook
    - ER diagram visualization with inferred relationships
    - Deep mode investigation results streamed as they complete

{'─' * 72}
  ONE-SHOT QUERY — mcpdb query
{'─' * 72}

  Run a single question and exit. Useful for scripting.

  mcpdb query <source> <question> [--no-cache]

  Examples:
    mcpdb query "postgres://u:p@h/db" "How many users signed up today?"
    mcpdb query sales.csv "Total revenue by region"
    mcpdb query data.xlsx "Average order value per customer"

{'─' * 72}
  INTERACTIVE REPL — mcpdb repl
{'─' * 72}

  Conversational interface with history, follow-ups, and mode control.

  mcpdb repl <source> [--no-cache]

  REPL commands:
    /help                   Show available commands
    /mode <mode|auto>       Override query mode (see QUERY MODES below)
    /source list            List connected sources
    /schema [table]         Show full or filtered schema
    /history                Show query history
    /export <markdown|json> Export last result
    /cache                  Show cache statistics
    /quit                   Exit

  Tip: Type a number (1, 2, 3) to pick a follow-up suggestion.

{'─' * 72}
  TEXTUAL TUI — mcpdb tui
{'─' * 72}

  Windowed terminal UI with source panel, pipeline bar, and result log.

  mcpdb tui <source> [--no-cache]

  Requires the textual package: pip install mcpdb[tui]

{'─' * 72}
  MCP SERVER — mcpdb serve
{'─' * 72}

  Runs MCPDB as a Model Context Protocol server for any
  MCP-compatible client.

  Options:
    --transport stdio|sse   Transport protocol (default: stdio)
    --port PORT             Port for SSE transport (default: 8765)

  Provides 30+ tools including: connect_database, execute_sql,
  ask_question, search_schema, render_erd, profile_table,
  find_relationships, export_conversation, and more.

{'─' * 72}
  QUERY MODES
{'─' * 72}

  MCPDB automatically classifies each question into the best mode:

  quick          Answer from known context (schema info, previous
                 results). Instant, no SQL execution.
                 Example: "What tables are in the database?"

  simple         Standard analytical query, 1-5 execution steps.
                 Default for most data questions.
                 Example: "What are the top 10 customers by revenue?"

  extended       Comprehensive analysis with 3-10 steps, iterative
                 refinement via checkpoint/revision loop.
                 Example: "Perform an EDA on the sales table"

  optimization   Large-table queries (>1M rows). Pauses for cost
                 gate strategy: SAMPLE, FULL, or CANCEL.
                 Example: "Analyze all 50M transaction records"

  deep           Multi-investigation research with 2-5 parallel
                 sub-investigations, blueprint-based reasoning.
                 Example: "Investigate customer churn patterns"

  In the REPL, override with: /mode simple  (or /mode auto to reset)
  In the web UI, select mode from the dropdown before submitting.

{'─' * 72}
  EXPERIENCE CACHE
{'─' * 72}

  MCPDB learns from successful queries. Identical or semantically
  similar questions return cached results instantly.

  Cache features:
    - Two-tier lookup: exact hash + semantic similarity
    - Mode-aware: won't serve a "quick" cache hit for a "deep" request
    - Schema drift detection: invalidates stale entries automatically
    - Quality evaluation: staged results scored before promotion

  Subcommands:
    mcpdb experience stats                    Show cache statistics
    mcpdb experience eval                     Evaluate pending results
    mcpdb experience clear --all              Clear everything
    mcpdb experience clear --source <fp>      Clear one source
    mcpdb experience export [--source <fp>]   Export as JSON
    mcpdb experience antipatterns             List failure patterns

  Flags:
    --no-cache       Skip cache lookup (still stores new results)

  Storage: ~/.mcpdb/experience/ (configurable via mcpdb.yaml)

{'─' * 72}
  EXPORT
{'─' * 72}

  After running queries in the web client, export your conversation:

  HTML       Self-contained single-file report with styling, tables,
             and embedded chart images. Opens in a new tab.

  PDF        Downloadable PDF document with full conversation.

  Notebook   Jupyter .ipynb with executable code cells:
             - Database/file connection setup
             - Schema overview queries
             - ER diagram (rendered via mermaid.js)
             - All SQL queries as runnable cells
             Optional: auto-launch Jupyter server

{'─' * 72}
  CONFIGURATION
{'─' * 72}

  Config file search order:
    1. MCPDB_CONFIG environment variable
    2. ./mcpdb.yaml in current directory
    3. Built-in defaults (no file needed)

  Key sections in mcpdb.yaml:

    llm:
      reasoning:
        provider: gemini          # gemini, openai, anthropic, ollama
        model: gemini-2.5-pro
      fast:
        provider: gemini
        model: gemini-2.5-flash

    execution:
      query_timeout: 30           # SQL query timeout (seconds)
      python_timeout: 60          # Python sandbox timeout
      max_rows_display: 100       # Max rows in result display
      read_only: true             # Block INSERT/UPDATE/DELETE

    cost_gate:
      enabled: true
      large_table_threshold: 1000000

    experience:
      enabled: true
      storage_dir: ~/.mcpdb/experience
      cache_max_age_days: 30
      quality_eval_min_score: 7

    sandbox:
      memory_mb: 2048
      cpu_seconds: 60

{'─' * 72}
  ENVIRONMENT VARIABLES
{'─' * 72}

  GEMINI_API_KEY        API key for Google Gemini (default provider)
  OPENAI_API_KEY        API key for OpenAI models
  ANTHROPIC_API_KEY     API key for Anthropic models
  MCPDB_CONFIG          Path to mcpdb.yaml config file
  MCPDB_DATABASE_URL    Pre-fill database URL in web UI

  API keys can also be set in mcpdb.yaml under llm.reasoning.api_key.
  Environment variables take precedence when the config value is empty.

{'─' * 72}
  SUPPORTED DATABASES
{'─' * 72}

  PostgreSQL      postgresql://user:pass@host:5432/dbname
  MySQL           mysql+pymysql://user:pass@host:3306/dbname
  SQLite          sqlite:///path/to/database.db
  SQL Server      mssql+pymssql://user:pass@host/dbname
  Oracle          oracle+oracledb://user:pass@host:1521/service

  File sources:
  CSV/TSV         path/to/file.csv  (or comma-separated list)
  Excel           path/to/workbook.xlsx

  CSV and Excel files are loaded into DuckDB for SQL querying.
  Multiple CSV files can be joined across tables.

{'─' * 72}
  SAFETY & SECURITY
{'─' * 72}

  - Read-only mode by default (no INSERT/UPDATE/DELETE)
  - Python code executes in a sandboxed environment
  - Dangerous modules blocked (os, subprocess, socket, etc.)
  - File uploads limited to 500MB with automatic cleanup
  - Query timeout: 10 minutes max
  - HTML output sanitized against XSS

{'─' * 72}
  MORE INFO
{'─' * 72}

  Short usage:     mcpdb --help
  Version:         mcpdb --version
  Source & issues:  https://github.com/nickolay/mcpdb

{'=' * 72}
"""


def _apply_sandbox_config(config) -> None:
    """Apply sandbox config to the security module."""
    from mcpdb.sandbox.security import configure_security, DEFAULT_ALLOWED_MODULES, DEFAULT_BLOCKED_MODULES

    sandbox = config.sandbox
    allowed = DEFAULT_ALLOWED_MODULES | frozenset(sandbox.allowed_modules)
    blocked = DEFAULT_BLOCKED_MODULES | frozenset(sandbox.blocked_modules)
    configure_security(
        allowed=allowed,
        blocked=blocked,
        allow_all=sandbox.allow_all,
    )


def main() -> None:
    from mcpdb.secrets import load_dotenv_if_available
    load_dotenv_if_available()

    logger = setup_logging()
    config = load_config()
    _apply_sandbox_config(config)

    args = sys.argv[1:]

    if not args:
        print(f"mcpdb v{__version__}")
        return

    command = args[0]

    if command == "serve":
        transport = "stdio"
        port = config.server.port

        i = 1
        while i < len(args):
            if args[i] == "--transport" and i + 1 < len(args):
                transport = args[i + 1]
                i += 2
            elif args[i] == "--port" and i + 1 < len(args):
                port = int(args[i + 1])
                i += 2
            else:
                i += 1

        logger.info("mcpdb v%s starting (transport=%s)", __version__, transport)

        if transport == "stdio":
            import asyncio
            from mcpdb.mcp.server import run_stdio_server
            asyncio.run(run_stdio_server(config))
        elif transport == "sse":
            import asyncio
            from mcpdb.mcp.server import run_sse_server
            try:
                asyncio.run(run_sse_server(config, port=port))
            except AttributeError:
                logger.error("SSE transport not yet implemented in server module")
                sys.exit(1)
        else:
            print(f"Unknown transport: {transport}")
            sys.exit(1)

    elif command == "web":
        port = None
        no_browser = False
        no_cache = False

        i = 1
        while i < len(args):
            if args[i] == "--port" and i + 1 < len(args):
                port = int(args[i + 1])
                i += 2
            elif args[i] == "--no-browser":
                no_browser = True
                i += 1
            elif args[i] == "--no-cache":
                no_cache = True
                i += 1
            else:
                i += 1

        try:
            from mcpdb.web.app import run_web, find_available_port
        except ImportError:
            print("Web client requires FastAPI + Uvicorn. Install with: pip install mcpdb[web]")
            sys.exit(1)

        if port is None:
            port = find_available_port()

        logger.info("mcpdb v%s web client starting on port %d", __version__, port)
        run_web(config=config, port=port, open_browser=not no_browser, no_cache=no_cache)

    elif command in ("ui", "webchat", "playground"):
        print(f"The '{command}' command has been removed. Use 'mcpdb web' instead.")
        sys.exit(1)

    elif command == "clean_cache":
        _clean_cache(config, args[1:])

    elif command == "query":
        if len(args) < 3:
            print("Usage: mcpdb query <connection_string> <question> [--no-cache]")
            sys.exit(1)

        # Suppress INFO logs in query mode — spinner handles status display
        import logging as _logging
        _logging.getLogger("mcpdb").setLevel(_logging.WARNING)
        for h in _logging.getLogger("mcpdb").handlers:
            h.setLevel(_logging.WARNING)
        # Also suppress google SDK info messages
        _logging.getLogger("google_genai").setLevel(_logging.WARNING)

        # Parse --no-cache flag from remaining args
        no_cache = "--no-cache" in args
        remaining = [a for a in args[1:] if a != "--no-cache"]
        connection_string = remaining[0]
        question = " ".join(remaining[1:])

        # Detect file-based sources by extension
        _CSV_EXTS = {".csv", ".tsv", ".tab"}
        _EXCEL_EXTS = {".xlsx", ".xls"}
        candidate_paths = [p.strip() for p in connection_string.split(",")]
        ext = Path(candidate_paths[0]).suffix.lower()

        if all(Path(p).suffix.lower() in _CSV_EXTS for p in candidate_paths) and all(Path(p).exists() for p in candidate_paths):
            _oneshot_csv_query(candidate_paths, question, config, logger, no_cache=no_cache)
        elif ext in _EXCEL_EXTS and Path(candidate_paths[0]).exists():
            _oneshot_excel_query(candidate_paths[0], question, config, logger, no_cache=no_cache)
        else:
            _oneshot_query(connection_string, question, config, logger, no_cache=no_cache)

    elif command == "repl":
        if len(args) < 2:
            print("Usage: mcpdb repl <connection_string_or_file>")
            sys.exit(1)

        # Suppress INFO logs — Rich UI handles status
        import logging as _logging
        _logging.getLogger("mcpdb").setLevel(_logging.WARNING)
        for h in _logging.getLogger("mcpdb").handlers:
            h.setLevel(_logging.WARNING)
        _logging.getLogger("google_genai").setLevel(_logging.WARNING)

        no_cache = "--no-cache" in args
        remaining = [a for a in args[1:] if a != "--no-cache"]
        connection_string = remaining[0]

        _start_repl(connection_string, config, logger, no_cache=no_cache)

    elif command == "tui":
        if len(args) < 2:
            print("Usage: mcpdb tui <connection_string_or_file>")
            sys.exit(1)

        # Suppress INFO logs — TUI handles status
        import logging as _logging
        _logging.getLogger("mcpdb").setLevel(_logging.WARNING)
        for h in _logging.getLogger("mcpdb").handlers:
            h.setLevel(_logging.WARNING)
        _logging.getLogger("google_genai").setLevel(_logging.WARNING)

        no_cache = "--no-cache" in args
        remaining = [a for a in args[1:] if a != "--no-cache"]
        connection_string = remaining[0]

        _start_tui(connection_string, config, logger, no_cache=no_cache)

    elif command == "experience":
        if len(args) < 2:
            print("Usage: mcpdb experience <stats|eval|clear|export|antipatterns>")
            sys.exit(1)

        subcmd = args[1]
        sub_args = args[2:]

        if subcmd == "eval":
            _experience_eval(config, logger)
        elif subcmd == "stats":
            _experience_stats(config)
        elif subcmd == "clear":
            _experience_clear(config, sub_args)
        elif subcmd == "export":
            _experience_export(config, sub_args)
        elif subcmd == "antipatterns":
            _experience_antipatterns(config, sub_args)
        else:
            print(f"Unknown experience subcommand: {subcmd}")
            print("Available: stats, eval, clear, export, antipatterns")
            sys.exit(1)

    elif command == "help":
        print(MANUAL)

    elif command in ("--help", "-h"):
        print(USAGE)

    elif command in ("--version", "-V"):
        print(f"mcpdb v{__version__}")

    else:
        print(f"Unknown command: {command}")
        print(USAGE)
        sys.exit(1)


def _create_source_and_registry(connection_string: str, logger):
    """Create a source and registry from a connection string. Returns (registry, source)."""
    from mcpdb.sources.registry import SourceRegistry

    _CSV_EXTS = {".csv", ".tsv", ".tab"}
    _EXCEL_EXTS = {".xlsx", ".xls"}

    registry = SourceRegistry()
    candidate_paths = [p.strip() for p in connection_string.split(",")]
    ext = Path(candidate_paths[0]).suffix.lower()

    if all(Path(p).suffix.lower() in _CSV_EXTS for p in candidate_paths) and all(
        Path(p).exists() for p in candidate_paths
    ):
        from mcpdb.sources.csv.source import CsvSource

        names = [Path(p).stem for p in candidate_paths]
        display = ", ".join(names[:3])
        if len(names) > 3:
            display += f" (+{len(names) - 3} more)"
        source = CsvSource(candidate_paths, display_name=display)
        registry.add_source(source)
    elif ext in _EXCEL_EXTS and Path(candidate_paths[0]).exists():
        from mcpdb.sources.excel.source import ExcelSource

        source = ExcelSource(
            candidate_paths[0], display_name=Path(candidate_paths[0]).name
        )
        registry.add_source(source)
    else:
        from mcpdb.sources.database.source import DatabaseSource

        source = DatabaseSource(connection_string)
        registry.add_source(source)

    return registry


def _start_tui(connection_string: str, config, logger, no_cache: bool = False) -> None:
    """Start the Textual TUI."""
    try:
        from mcpdb.cli.tui.app import run_tui
    except ImportError:
        print("TUI requires textual. Install with: pip install mcpdb[tui]")
        sys.exit(1)

    from mcpdb.experience.service import ExperienceService
    from mcpdb.llm.factory import create_provider

    registry = _create_source_and_registry(connection_string, logger)

    try:
        llm_cfg = config.llm.reasoning
        llm = create_provider(
            llm_cfg.provider,
            llm_cfg.model,
            llm_cfg.api_key,
        )

        service = ExperienceService(config.experience)

        run_tui(
            registry=registry,
            llm=llm,
            config=config,
            experience_service=service,
            no_cache=no_cache,
        )
    finally:
        registry.close_all()


def _start_repl(connection_string: str, config, logger, no_cache: bool = False) -> None:
    """Start the interactive REPL."""
    from mcpdb.experience.service import ExperienceService
    from mcpdb.llm.factory import create_provider
    from mcpdb.cli.repl import Repl

    registry = _create_source_and_registry(connection_string, logger)

    try:
        llm_cfg = config.llm.reasoning
        llm = create_provider(
            llm_cfg.provider,
            llm_cfg.model,
            llm_cfg.api_key,
        )

        service = ExperienceService(config.experience)

        repl = Repl(
            registry=registry,
            llm=llm,
            config=config,
            experience_service=service,
            no_cache=no_cache,
        )
        repl.run()
    finally:
        registry.close_all()


def _oneshot_query(connection_string: str, question: str, config, logger, no_cache: bool = False) -> None:
    """Run a one-shot query and print the result."""
    import asyncio

    async def run():
        from mcpdb.sources.database.source import DatabaseSource
        from mcpdb.sources.registry import SourceRegistry
        from mcpdb.agent.graph import run_agent
        from mcpdb.agent.callbacks import CallbackManager
        from mcpdb.experience.service import ExperienceService
        from mcpdb.llm.factory import create_provider
        from mcpdb.cli.progress import RichProgress
        from mcpdb.cli.renderer import ResultRenderer

        progress = RichProgress(question=question, source_name=connection_string)
        callbacks = CallbackManager()
        callbacks.add_listener(progress.on_event)

        service = ExperienceService(config.experience)

        registry = SourceRegistry()
        try:
            source = DatabaseSource(connection_string)
            registry.add_source(source)
            logger.info("Connected to %s", connection_string)

            llm_cfg = config.llm.reasoning
            llm = create_provider(
                llm_cfg.provider,
                llm_cfg.model,
                llm_cfg.api_key,
            )

            progress.start()

            state = await run_agent(
                question, registry, llm, callbacks,
                experience_cache=service.cache,
                staging_store=service.staging,
                no_cache=no_cache,
            )
            response = state.get("response") or "No response generated."
            progress.finish(state)
            renderer = ResultRenderer()
            renderer.render_response(response)
            renderer.render_artifacts(state.get("artifacts", []))
        except Exception as e:
            progress.error(str(e))
            raise
        finally:
            registry.close_all()

    asyncio.run(run())


def _oneshot_csv_query(file_paths: list[str], question: str, config, logger, no_cache: bool = False) -> None:
    """Run a one-shot query against CSV/TSV file(s)."""
    import asyncio

    async def run():
        from mcpdb.sources.csv.source import CsvSource
        from mcpdb.sources.registry import SourceRegistry
        from mcpdb.agent.graph import run_agent
        from mcpdb.agent.callbacks import CallbackManager
        from mcpdb.experience.service import ExperienceService
        from mcpdb.llm.factory import create_provider
        from mcpdb.cli.progress import RichProgress
        from mcpdb.cli.renderer import ResultRenderer

        names = [Path(p).stem for p in file_paths]
        display = ", ".join(names[:3])
        if len(names) > 3:
            display += f" (+{len(names) - 3} more)"

        progress = RichProgress(question=question, source_name=display)
        callbacks = CallbackManager()
        callbacks.add_listener(progress.on_event)

        service = ExperienceService(config.experience)

        registry = SourceRegistry()
        try:
            source = CsvSource(file_paths, display_name=display)
            registry.add_source(source)
            logger.info("Loaded CSV: %s", display)

            llm_cfg = config.llm.reasoning
            llm = create_provider(
                llm_cfg.provider,
                llm_cfg.model,
                llm_cfg.api_key,
            )

            progress.start()

            state = await run_agent(
                question, registry, llm, callbacks,
                experience_cache=service.cache,
                staging_store=service.staging,
                no_cache=no_cache,
            )
            response = state.get("response") or "No response generated."
            progress.finish(state)
            renderer = ResultRenderer()
            renderer.render_response(response)
            renderer.render_artifacts(state.get("artifacts", []))
        except Exception as e:
            progress.error(str(e))
            raise
        finally:
            registry.close_all()

    asyncio.run(run())


def _oneshot_excel_query(file_path: str, question: str, config, logger, no_cache: bool = False) -> None:
    """Run a one-shot query against an Excel workbook."""
    import asyncio

    async def run():
        from mcpdb.sources.excel.source import ExcelSource
        from mcpdb.sources.registry import SourceRegistry
        from mcpdb.agent.graph import run_agent
        from mcpdb.agent.callbacks import CallbackManager
        from mcpdb.experience.service import ExperienceService
        from mcpdb.llm.factory import create_provider
        from mcpdb.cli.progress import RichProgress
        from mcpdb.cli.renderer import ResultRenderer

        display = Path(file_path).name
        progress = RichProgress(question=question, source_name=display)
        callbacks = CallbackManager()
        callbacks.add_listener(progress.on_event)

        service = ExperienceService(config.experience)

        registry = SourceRegistry()
        try:
            source = ExcelSource(file_path, display_name=display)
            registry.add_source(source)
            logger.info("Loaded Excel: %s", display)

            llm_cfg = config.llm.reasoning
            llm = create_provider(
                llm_cfg.provider,
                llm_cfg.model,
                llm_cfg.api_key,
            )

            progress.start()

            state = await run_agent(
                question, registry, llm, callbacks,
                experience_cache=service.cache,
                staging_store=service.staging,
                no_cache=no_cache,
            )
            response = state.get("response") or "No response generated."
            progress.finish(state)
            renderer = ResultRenderer()
            renderer.render_response(response)
            renderer.render_artifacts(state.get("artifacts", []))
        except Exception as e:
            progress.error(str(e))
            raise
        finally:
            registry.close_all()

    asyncio.run(run())


def _experience_eval(config, logger) -> None:
    """Evaluate all pending staged records."""
    import asyncio

    async def run():
        from mcpdb.experience.evaluator import QualityEvaluator
        from mcpdb.experience.service import ExperienceService
        from mcpdb.llm.factory import create_provider

        service = ExperienceService(config.experience)
        staging_store = service.staging
        experience_store = service.store
        experience_cache = service.cache
        evaluator = QualityEvaluator(min_score=config.experience.quality_eval_min_score)

        pending = staging_store.get_all_pending()
        if not pending:
            print("No pending staged records to evaluate.")
            return

        print(f"Found {len(pending)} pending staged record(s).")

        llm_cfg = config.llm.reasoning
        llm = create_provider(
            llm_cfg.provider,
            llm_cfg.model,
            llm_cfg.api_key,
        )

        promoted = 0
        rejected = 0
        errors = 0

        for record in pending:
            try:
                result = await evaluator.evaluate(record, llm)
            except Exception as e:
                print(f"  Error evaluating {record.question[:50]}: {e}")
                errors += 1
                continue

            fp = record.source_fingerprint
            ih = record.intent_hash

            if result.verdict == "promote":
                success = record.to_success_record()
                experience_store.store_success(success)
                staging_store.remove(fp, ih)
                promoted += 1
                print(f"  Promoted (score={result.score}): {record.question[:60]}")
            else:
                from mcpdb.experience.records import FailureRecord
                experience_store.store_failure(FailureRecord(
                    question=record.question,
                    source_fingerprint=fp,
                    error_type="quality_rejected",
                    error_message=(
                        f"Score {result.score}/10. "
                        f"Issues: {'; '.join(result.issues) if result.issues else 'none'}"
                    ),
                    failed_code=record.response[:500],
                ))
                staging_store.remove(fp, ih)
                rejected += 1
                print(f"  Rejected (score={result.score}): {record.question[:60]}")

        print(f"\nDone: {promoted} promoted, {rejected} rejected, {errors} errors.")

    asyncio.run(run())


def _experience_stats(config) -> None:
    """Show experience cache and staging statistics."""
    from mcpdb.experience.service import ExperienceService

    service = ExperienceService(config.experience)
    store = service.store
    staging = service.staging
    cache = service.cache

    fingerprints = store.list_fingerprints()

    if not fingerprints:
        print("No experience data found.")
    else:
        print(f"Experience store ({len(fingerprints)} source(s)):")
        print(f"  {'Fingerprint':<20s} {'Successes':>10s} {'Failures':>10s} {'Oldest':>12s} {'Newest':>12s}")
        print(f"  {'─' * 20} {'─' * 10} {'─' * 10} {'─' * 12} {'─' * 12}")
        for fp in fingerprints:
            stats = store.get_stats(fp)
            import time as _time
            oldest = _time.strftime("%Y-%m-%d", _time.localtime(stats["oldest"])) if stats["oldest"] else "n/a"
            newest = _time.strftime("%Y-%m-%d", _time.localtime(stats["newest"])) if stats["newest"] else "n/a"
            print(f"  {fp[:20]:<20s} {stats['successes']:>10d} {stats['failures']:>10d} {oldest:>12s} {newest:>12s}")

    # Staging stats
    pending = staging.get_all_pending()
    staging_fps = staging.list_fingerprints()
    print(f"\nStaging: {len(pending)} pending record(s) across {len(staging_fps)} source(s)")

    # Cache memory stats
    cache_stats = cache.get_stats()
    print(f"Memory cache: {cache_stats['memory_entries']}/{cache_stats['memory_max']} entries")


def _experience_clear(config, sub_args: list[str]) -> None:
    """Clear experience and staging data."""
    from mcpdb.experience.service import ExperienceService

    service = ExperienceService(config.experience)
    store = service.store
    staging = service.staging

    source_fp = None
    clear_all = False

    i = 0
    while i < len(sub_args):
        if sub_args[i] == "--all":
            clear_all = True
            i += 1
        elif sub_args[i] == "--source" and i + 1 < len(sub_args):
            source_fp = sub_args[i + 1]
            i += 2
        else:
            i += 1

    if source_fp:
        store.clear(source_fp)
        # Clear staging for this fingerprint
        for record in staging.get_all(source_fp):
            staging.remove(source_fp, record.intent_hash)
        print(f"Cleared experience data for source: {source_fp}")
    elif clear_all:
        count = 0
        for fp in store.list_fingerprints():
            store.clear(fp)
            count += 1
        for fp in staging.list_fingerprints():
            for record in staging.get_all(fp):
                staging.remove(fp, record.intent_hash)
            count += 1
        print(f"Cleared all experience data ({count} source(s)).")
    else:
        print("Usage: mcpdb experience clear --all")
        print("       mcpdb experience clear --source <fingerprint>")
        print("\nUse 'mcpdb experience stats' to see available fingerprints.")
        sys.exit(1)


def _experience_export(config, sub_args: list[str]) -> None:
    """Export experience data as JSON to stdout."""
    import json
    from mcpdb.experience.service import ExperienceService

    service = ExperienceService(config.experience)
    store = service.store
    staging = service.staging

    source_fp = None
    i = 0
    while i < len(sub_args):
        if sub_args[i] == "--source" and i + 1 < len(sub_args):
            source_fp = sub_args[i + 1]
            i += 2
        else:
            i += 1

    all_records = []

    if source_fp:
        fingerprints = [source_fp]
    else:
        fingerprints = store.list_fingerprints()

    for fp in fingerprints:
        records = store._load_records(fp)
        all_records.extend(records)

    # Include staged records
    staging_fps = [source_fp] if source_fp else staging.list_fingerprints()
    for fp in staging_fps:
        for record in staging.get_all(fp):
            d = record.to_dict()
            d["status"] = "staged"
            all_records.append(d)

    print(json.dumps(all_records, indent=2))


def _experience_antipatterns(config, sub_args: list[str]) -> None:
    """List anti-patterns with counts and avoidance hints."""
    from collections import Counter
    from mcpdb.experience.antipatterns import _simplify_error, _generate_hint
    from mcpdb.experience.records import FailureRecord
    from mcpdb.experience.service import ExperienceService

    service = ExperienceService(config.experience)
    store = service.store

    source_fp = None
    i = 0
    while i < len(sub_args):
        if sub_args[i] == "--source" and i + 1 < len(sub_args):
            source_fp = sub_args[i + 1]
            i += 2
        else:
            i += 1

    if source_fp:
        fingerprints = [source_fp]
    else:
        fingerprints = store.list_fingerprints()

    if not fingerprints:
        print("No experience data found.")
        return

    # Collect all failures across sources
    pattern_counts: Counter[str] = Counter()
    pattern_examples: dict[str, FailureRecord] = {}

    for fp in fingerprints:
        failures = store.get_failures(fp)
        for f in failures:
            key = f"{f.error_type}:{_simplify_error(f.error_message)}"
            pattern_counts[key] += 1
            pattern_examples[key] = f

    if not pattern_counts:
        print("No failure patterns found.")
        return

    # Show all patterns sorted by count
    min_occ = config.experience.anti_pattern_min_occurrences
    promoted = [(k, c) for k, c in pattern_counts.most_common() if c >= min_occ]
    below = [(k, c) for k, c in pattern_counts.most_common() if c < min_occ]

    if promoted:
        print(f"Anti-patterns (promoted, >= {min_occ} occurrences):")
        for key, count in promoted:
            example = pattern_examples[key]
            hint = _generate_hint(example)
            print(f"\n  [{example.error_type}] {_simplify_error(example.error_message)}")
            print(f"    Occurrences: {count}")
            print(f"    Hint: {hint}")
            if example.failed_code:
                print(f"    Example code: {example.failed_code[:100]}")
    else:
        print("No promoted anti-patterns yet.")

    if below:
        print(f"\nPending patterns (< {min_occ} occurrences):")
        for key, count in below:
            example = pattern_examples[key]
            print(f"  [{example.error_type}] {_simplify_error(example.error_message)} ({count}x)")


def _clean_cache(config, sub_args: list[str]) -> None:
    """Clear experience cache, staging, and store data."""
    from mcpdb.experience.service import ExperienceService

    service = ExperienceService(config.experience)
    store = service.store
    staging = service.staging
    cache = service.cache

    source_fp = None
    stats_only = False

    i = 0
    while i < len(sub_args):
        if sub_args[i] == "--source" and i + 1 < len(sub_args):
            source_fp = sub_args[i + 1]
            i += 2
        elif sub_args[i] == "--stats":
            stats_only = True
            i += 1
        else:
            i += 1

    if stats_only:
        _print_cache_stats(store, staging, cache)
        return

    if source_fp:
        # Clear one source
        store.clear(source_fp)
        for record in staging.get_all(source_fp):
            staging.remove(source_fp, record.intent_hash)
        cache.clear_source_by_fingerprint(source_fp)
        print(f"Cleared cache for source: {source_fp}")
    else:
        # Clear everything
        cleared_sources = 0
        for fp in store.list_fingerprints():
            store.clear(fp)
            cleared_sources += 1
        cleared_staging = 0
        for fp in staging.list_fingerprints():
            for record in staging.get_all(fp):
                staging.remove(fp, record.intent_hash)
                cleared_staging += 1
        cache.clear_all()
        print(f"Cache cleared: {cleared_sources} source(s), {cleared_staging} staged record(s) removed.")


def _print_cache_stats(store, staging, cache) -> None:
    """Print cache statistics."""
    fingerprints = store.list_fingerprints()
    cache_stats = cache.get_stats()

    if not fingerprints:
        print("No cached experience data.")
    else:
        total_success = 0
        total_failure = 0
        for fp in fingerprints:
            stats = store.get_stats(fp)
            total_success += stats["successes"]
            total_failure += stats["failures"]
        print(f"Cache: {total_success} cached solution(s), {total_failure} failure record(s) across {len(fingerprints)} source(s)")

    pending = staging.get_all_pending()
    print(f"Staging: {len(pending)} pending record(s)")
    print(f"Memory: {cache_stats['memory_entries']}/{cache_stats['memory_max']} entries loaded")


if __name__ == "__main__":
    main()
