"""Interactive REPL for mcpdb."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from rich.console import Console

from mcpdb.cli.progress import RichProgress
from mcpdb.cli.renderer import ResultRenderer


class Repl:
    """Interactive REPL for mcpdb queries.

    Supports slash commands, follow-up suggestions by number,
    and optional prompt_toolkit for history and key bindings.
    """

    COMMANDS = {
        "/help": "Show available commands",
        "/mode": "Set mode override (e.g. /mode simple, /mode auto)",
        "/source": "List connected sources (/source list)",
        "/history": "Show query history",
        "/export": "Export last result (/export markdown, /export json)",
        "/cache": "Show cache statistics",
        "/schema": "Show schema (/schema or /schema <table>)",
        "/quit": "Exit REPL",
    }

    def __init__(
        self,
        registry: Any,
        llm: Any,
        config: Any,
        experience_service: Any | None = None,
        no_cache: bool = False,
    ) -> None:
        self._registry = registry
        self._llm = llm
        self._config = config
        self._experience = experience_service
        self._no_cache = no_cache
        self._console = Console()
        self._renderer = ResultRenderer(self._console)
        self._history: list[dict[str, Any]] = []
        self._last_result: dict[str, Any] | None = None
        self._last_followups: list[str] = []
        self._mode_override: str | None = None

    def run(self) -> None:
        """Run the REPL event loop."""
        asyncio.run(self._async_run())

    async def _async_run(self) -> None:
        """Async REPL main loop."""
        self._print_banner()

        # Try prompt_toolkit for better input handling
        session = None
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.history import InMemoryHistory
            session = PromptSession(history=InMemoryHistory())
        except ImportError:
            pass

        loop = asyncio.get_event_loop()

        while True:
            try:
                if session:
                    user_input = await session.prompt_async("mcpdb> ")
                else:
                    user_input = await loop.run_in_executor(
                        None, lambda: input("mcpdb> ")
                    )
            except (EOFError, KeyboardInterrupt):
                self._console.print("\n[dim]Goodbye![/dim]")
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            # Follow-up selection by number
            if user_input.isdigit():
                idx = int(user_input) - 1
                if 0 <= idx < len(self._last_followups):
                    user_input = self._last_followups[idx]
                    self._console.print(f"[dim]→ {user_input}[/dim]")
                else:
                    n = len(self._last_followups)
                    if n:
                        self._console.print(
                            f"[red]Invalid suggestion. Available: 1-{n}[/red]"
                        )
                    else:
                        self._console.print("[red]No suggestions available.[/red]")
                    continue

            # Handle commands
            if user_input.startswith("/"):
                if user_input.split()[0].lower() in ("/quit", "/exit", "/q"):
                    self._console.print("[dim]Goodbye![/dim]")
                    break
                self._handle_command(user_input)
                continue

            # Run query
            await self._run_query(user_input)

    def _print_banner(self) -> None:
        """Print the REPL welcome banner."""
        from mcpdb import __version__

        sources = self._registry.list_sources()

        self._console.print(
            f"[bold blue]mcpdb[/bold blue] v{__version__} — Interactive Mode"
        )
        if sources:
            for s in sources:
                self._console.print(f"  [green]●[/green] {s.display_name}")
        self._console.print(
            "[dim]Type a question, a number to select a suggestion, or /help[/dim]"
        )
        self._console.print()

    def _handle_command(self, cmd: str) -> None:
        """Handle a slash command."""
        parts = cmd.split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if command == "/help":
            for name, desc in self.COMMANDS.items():
                self._console.print(f"  [cyan]{name}[/cyan]  {desc}")

        elif command == "/mode":
            if not arg:
                current = self._mode_override or "auto"
                self._console.print(f"Current mode: [bold]{current}[/bold]")
                self._console.print(
                    "[dim]Usage: /mode <quick|simple|extended|optimization|deep|auto>[/dim]"
                )
            elif arg in ("auto", "none", "reset"):
                self._mode_override = None
                self._console.print("Mode: [bold]auto[/bold]")
            else:
                self._mode_override = arg
                self._console.print(f"Mode override: [bold]{arg}[/bold]")

        elif command == "/history":
            if not self._history:
                self._console.print("[dim]No queries yet.[/dim]")
            else:
                for i, entry in enumerate(self._history, 1):
                    mode = entry.get("mode", "?")
                    elapsed = entry.get("elapsed", 0)
                    q = entry.get("question", "")[:60]
                    self._console.print(f"  {i}. [{mode}] {q} ({elapsed:.1f}s)")

        elif command == "/cache":
            if self._experience:
                stats = self._experience.cache.get_stats()
                self._console.print(
                    f"Cache: {stats['memory_entries']}/{stats['memory_max']} entries"
                )
            else:
                self._console.print("[dim]No experience service configured.[/dim]")

        elif command == "/source":
            sources = self._registry.list_sources()
            if sources:
                for s in sources:
                    self._console.print(f"  [green]●[/green] {s.display_name}")
            else:
                self._console.print("[dim]No sources connected.[/dim]")

        elif command == "/export":
            if not self._last_result:
                self._console.print("[dim]No result to export.[/dim]")
                return
            fmt = arg or "markdown"
            response = self._last_result.get("response", "")
            if fmt in ("markdown", "md"):
                self._console.print(response)
            elif fmt == "json":
                import json
                print(json.dumps(self._last_result, indent=2, default=str))
            else:
                self._console.print(
                    f"[dim]Unsupported format: {fmt}. Use: markdown, json[/dim]"
                )

        elif command == "/schema":
            self._show_schema(arg)

        else:
            self._console.print(
                f"[dim]Unknown command: {command}. Type /help for commands.[/dim]"
            )

    def _show_schema(self, table_name: str) -> None:
        """Show schema for a table or all tables."""
        sources = self._registry.list_sources()
        if not sources:
            self._console.print("[dim]No sources connected.[/dim]")
            return

        metadata = sources[0]  # list_sources returns SourceMetadata list

        if table_name:
            for tinfo in metadata.tables:
                if tinfo.name.lower() == table_name.lower():
                    from rich.table import Table

                    rt = Table(title=tinfo.name)
                    rt.add_column("Column", style="cyan")
                    rt.add_column("Type")
                    rt.add_column("Nullable")
                    for col in tinfo.columns:
                        nullable = "✓" if col.nullable else ""
                        rt.add_row(col.name, col.dtype, nullable)
                    self._console.print(rt)
                    if tinfo.row_count is not None:
                        self._console.print(f"  [dim]({tinfo.row_count} rows)[/dim]")
                    return
            self._console.print(f"[dim]Table '{table_name}' not found.[/dim]")
        else:
            self._renderer.render_table_list(metadata)

    async def _run_query(self, question: str) -> None:
        """Execute a query and display results."""
        from mcpdb.agent.callbacks import CallbackManager
        from mcpdb.agent.graph import run_agent

        progress = RichProgress(question=question)
        callbacks = CallbackManager()
        callbacks.add_listener(progress.on_event)

        progress.start()
        start = time.time()

        try:
            state = await run_agent(
                question,
                self._registry,
                self._llm,
                callbacks,
                mode_override=self._mode_override,
                experience_cache=(
                    self._experience.cache if self._experience else None
                ),
                staging_store=(
                    self._experience.staging if self._experience else None
                ),
                no_cache=self._no_cache,
            )
        except KeyboardInterrupt:
            progress.error("Cancelled by user")
            return
        except Exception as e:
            progress.error(str(e))
            return

        elapsed = time.time() - start
        progress.finish(state)

        # Display result
        response = state.get("response") or "No response generated."
        followups = self._generate_followups(question, response, state)

        self._renderer.render_response(response, followups)
        self._renderer.render_artifacts(state.get("artifacts", []))

        # Show token usage
        usage = state.get("llm_usage")
        if usage and usage.get("calls"):
            from mcpdb.cli.progress import fmt_tokens
            total = usage.get("total_tokens", 0)
            inp = usage.get("input_tokens", 0)
            out = usage.get("output_tokens", 0)
            self._console.print(
                f"[dim]{usage['calls']} LLM calls · "
                f"{fmt_tokens(inp)} in / {fmt_tokens(out)} out · "
                f"{elapsed:.1f}s[/dim]"
            )

        # Store history
        self._history.append({
            "question": question,
            "mode": state.get("query_mode", "?"),
            "elapsed": elapsed,
            "response": response,
            "llm_usage": usage,
        })
        self._last_result = {
            "question": question,
            "response": response,
            "query_mode": state.get("query_mode"),
            "artifacts": state.get("artifacts", []),
            "llm_usage": usage,
        }
        self._last_followups = followups

    def _generate_followups(
        self, question: str, response: str, state: dict[str, Any]
    ) -> list[str]:
        """Generate follow-up suggestions based on the query and response."""
        followups = []
        mode = state.get("query_mode", "")
        q_lower = question.lower()

        if "table" in response.lower() or "|" in response:
            followups.append("Show this as a chart")
        if any(kw in q_lower for kw in ("average", "mean", "sum", "count")):
            followups.append("Break this down by year/month")
        if any(kw in q_lower for kw in ("top", "highest", "largest", "most")):
            followups.append("Show the bottom/lowest instead")
        if mode == "simple":
            followups.append("Do a deeper investigation on this topic")

        return followups[:3]
