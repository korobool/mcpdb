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
  mcpdb serve                    Start MCP server (stdio, for Claude Desktop)
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

    elif command in ("--help", "-h", "help"):
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
