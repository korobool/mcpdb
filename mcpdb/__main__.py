"""MCPDB CLI entry point."""

from __future__ import annotations

import sys
import warnings

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
  mcpdb ui                       Start the web UI
  mcpdb ui --port 8080           Start UI on custom port
  mcpdb query <conn> <question>  One-shot query mode
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

    elif command == "ui":
        port = 8080
        theme = "dark"

        i = 1
        while i < len(args):
            if args[i] == "--port" and i + 1 < len(args):
                port = int(args[i + 1])
                i += 2
            elif args[i] == "--theme" and i + 1 < len(args):
                theme = args[i + 1]
                i += 2
            else:
                i += 1

        logger.info("mcpdb v%s UI starting on port %d", __version__, port)
        try:
            from mcpdb.ui.app import run_ui
            run_ui(port=port, theme=theme, config=config)
        except ImportError:
            print("UI requires NiceGUI. Install with: pip install mcpdb[ui]")
            sys.exit(1)

    elif command == "query":
        if len(args) < 3:
            print("Usage: mcpdb query <connection_string> <question>")
            sys.exit(1)

        # Suppress INFO logs in query mode — spinner handles status display
        import logging as _logging
        _logging.getLogger("mcpdb").setLevel(_logging.WARNING)
        for h in _logging.getLogger("mcpdb").handlers:
            h.setLevel(_logging.WARNING)
        # Also suppress google SDK info messages
        _logging.getLogger("google_genai").setLevel(_logging.WARNING)

        connection_string = args[1]
        question = " ".join(args[2:])
        _oneshot_query(connection_string, question, config, logger)

    elif command in ("--help", "-h", "help"):
        print(USAGE)

    elif command in ("--version", "-V"):
        print(f"mcpdb v{__version__}")

    else:
        print(f"Unknown command: {command}")
        print(USAGE)
        sys.exit(1)


class _ConsoleProgress:
    """Live console progress indicator using agent callback events."""

    SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    # Map event types to human-readable status messages
    LABELS = {
        "classify/start": "Classifying question",
        "classify/complete": None,  # handled specially
        "plan/start": "Planning analysis",
        "plan/ready": None,
        "plan/retry": "Retrying plan",
        "plan/error": "Plan failed, using fallback",
        "step/start": None,  # handled specially
        "step/complete": None,
        "step/error": None,
        "debug/start": "Debugging failed step",
        "debug/fixed": "Fix applied",
        "debug/give_up": "Skipping failed step",
        "checkpoint/start": "Reviewing progress",
        "checkpoint/complete": None,
        "revise/start": "Revising plan",
        "revise/ready": None,
        "reflect/start": "Reflecting on results",
        "reflect/ready": None,
        "validate/start": "Validating results",
        "validate/adequate": None,
        "validate/inadequate": "Results incomplete, replanning",
        "replan/start": "Creating corrected plan",
        "replan/ready": None,
        "synthesize/start": "Synthesizing response",
        "synthesize/complete": None,
        "extended/start": None,
        "extended/complete": None,
        "agent/complete": None,
        "experience/cache_hit": "Using cached result",
        "quick/start": "Answering from context",
        "quick/complete": None,
        "quick/escalate": "Escalating to full analysis",
    }

    def __init__(self) -> None:
        import threading
        self._lock = threading.Lock()
        self._spin_idx = 0
        self._current_msg = ""
        self._step_count = 0
        self._steps_done = 0
        self._mode = ""
        self._start_time = 0.0

    def on_event(self, event) -> None:
        import time
        etype = event.type
        data = event.data

        if self._start_time == 0.0:
            self._start_time = time.time()

        msg = None

        if etype == "classify/complete":
            self._mode = data.get("mode", "")
            msg = f"Mode: {self._mode}"
        elif etype == "plan/ready":
            self._step_count = data.get("step_count", 0)
            msg = f"Plan ready — {self._step_count} steps"
        elif etype == "step/start":
            step_num = data.get("step_number", "?")
            action = data.get("action", "")
            total = self._step_count or "?"
            msg = f"Step {step_num}/{total} ({action})"
        elif etype == "step/complete":
            self._steps_done += 1
            step_num = data.get("step_number", "?")
            ms = data.get("time_ms", 0)
            msg = f"Step {step_num} done ({ms}ms)"
        elif etype == "step/error":
            step_num = data.get("step_number", "?")
            err = data.get("error", "")[:60]
            msg = f"Step {step_num} error: {err}"
        elif etype == "replan/ready":
            self._step_count = data.get("step_count", 0)
            self._steps_done = 0
            msg = f"New plan — {self._step_count} steps"
        elif etype == "revise/ready":
            new = data.get("new_step_count", 0)
            msg = f"Revised — {new} steps remaining"
        elif etype == "checkpoint/complete":
            action = data.get("action", "")
            if action == "done":
                msg = "Checkpoint: stopping early"
        elif etype in self.LABELS:
            msg = self.LABELS[etype]
        # None means skip (no status update for this event)

        if msg is not None:
            self._print_status(msg)

    def _print_status(self, msg: str) -> None:
        import time
        with self._lock:
            self._spin_idx = (self._spin_idx + 1) % len(self.SPINNER)
            spinner = self.SPINNER[self._spin_idx]
            elapsed = time.time() - self._start_time if self._start_time else 0
            line = f"\r\033[K  {spinner} {msg}  [{elapsed:.0f}s]"
            sys.stderr.write(line)
            sys.stderr.flush()
            self._current_msg = msg

    def finish(self) -> None:
        import time
        elapsed = time.time() - self._start_time if self._start_time else 0
        sys.stderr.write(f"\r\033[K  ✓ Done — {self._steps_done} steps in {elapsed:.0f}s\n")
        sys.stderr.flush()

    def error(self, msg: str) -> None:
        sys.stderr.write(f"\r\033[K  ✗ {msg}\n")
        sys.stderr.flush()


def _oneshot_query(connection_string: str, question: str, config, logger) -> None:
    """Run a one-shot query and print the result."""
    import asyncio

    async def run():
        from mcpdb.sources.database.source import DatabaseSource
        from mcpdb.sources.registry import SourceRegistry
        from mcpdb.agent.graph import run_agent
        from mcpdb.agent.callbacks import CallbackManager
        from mcpdb.llm.factory import create_provider

        progress = _ConsoleProgress()
        callbacks = CallbackManager()
        callbacks.add_listener(progress.on_event)

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

            state = await run_agent(question, registry, llm, callbacks)
            response = state.get("response") or "No response generated."
            progress.finish()
            print(response)
        except Exception as e:
            progress.error(str(e))
            raise
        finally:
            registry.close_all()

    asyncio.run(run())


if __name__ == "__main__":
    main()
