"""Textual TUI application for mcpdb."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.worker import Worker, WorkerState
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Footer,
    Header,
    Input,
    RichLog,
    Static,
)

from mcpdb.cli.progress import MODE_COLORS


class SourcePanel(Static):
    """Panel showing connected data sources."""

    DEFAULT_CSS = """
    SourcePanel {
        width: 1fr;
        height: auto;
        min-height: 3;
        border: solid $accent;
        padding: 0 1;
    }
    """

    def __init__(self, sources: list[Any] | None = None, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self._sources = sources or []

    def on_mount(self) -> None:
        self.update(self._render_sources())

    def _render_sources(self) -> Text:
        text = Text()
        if not self._sources:
            text.append("No sources connected", style="dim")
        else:
            for s in self._sources:
                name = s.display_name if hasattr(s, "display_name") else str(s)
                stype = s.source_type.value if hasattr(s, "source_type") else "?"
                tables = len(s.tables) if hasattr(s, "tables") else 0
                text.append("● ", style="green")
                text.append(f"{name} ", style="bold")
                text.append(f"({stype}, {tables} tables)\n", style="dim")
        return text

    def update_sources(self, sources: list[Any]) -> None:
        self._sources = sources
        self.update(self._render_sources())


class PipelineBar(Static):
    """Shows the current pipeline phase status."""

    DEFAULT_CSS = """
    PipelineBar {
        width: 1fr;
        height: auto;
        min-height: 3;
        border: solid $accent;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self._phases = {
            "classify": ("◌", "dim"),
            "plan": ("◌", "dim"),
            "execute": ("◌", "dim"),
            "synthesize": ("◌", "dim"),
        }
        self._mode = ""
        self._detail = ""
        self._step_info = ""

    def on_mount(self) -> None:
        self.update(self._build_text())

    def _build_text(self) -> Text:
        text = Text()

        if self._mode:
            color = MODE_COLORS.get(self._mode, "white")
            text.append("Mode: ", style="dim")
            text.append(self._mode, style=f"bold {color}")
            text.append("\n")

        for name, (icon, style) in self._phases.items():
            text.append(f" {icon} ", style=style)
            text.append(f"{name.title()}", style=style)
            text.append("  ")

        if self._detail:
            text.append(f"\n{self._detail}", style="dim")
        if self._step_info:
            text.append(f"\n{self._step_info}", style="cyan")

        return text

    def update_phase(self, phase: str, icon: str, style: str, detail: str = "") -> None:
        if phase in self._phases:
            self._phases[phase] = (icon, style)
        if detail:
            self._detail = detail
        self.update(self._build_text())

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.update(self._build_text())

    def set_step_info(self, info: str) -> None:
        self._step_info = info
        self.update(self._build_text())

    def reset(self) -> None:
        for k in self._phases:
            self._phases[k] = ("◌", "dim")
        self._mode = ""
        self._detail = ""
        self._step_info = ""
        self.update(self._build_text())


class McpdbTUI(App):
    """Textual TUI application for mcpdb."""

    CSS = """
    #main-container {
        layout: grid;
        grid-size: 1;
        grid-gutter: 1;
    }

    #top-row {
        layout: horizontal;
        height: auto;
        min-height: 5;
    }

    #source-panel {
        width: 30%;
    }

    #pipeline-panel {
        width: 70%;
    }

    #result-log {
        height: 1fr;
        min-height: 10;
        border: solid $accent;
    }

    #event-log {
        height: 8;
        border: solid $surface;
    }

    #query-input {
        dock: bottom;
        margin: 0 0;
    }

    #stats-bar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "cancel_query", "Cancel Query"),
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+l", "clear_results", "Clear"),
    ]

    def __init__(
        self,
        registry: Any,
        llm: Any,
        config: Any,
        experience_service: Any | None = None,
        no_cache: bool = False,
        knowledge_manager: Any = None,
    ) -> None:
        super().__init__()
        self._source_registry = registry
        self._llm = llm
        self._config = config
        self._experience = experience_service
        self._no_cache = no_cache
        self._knowledge_manager = knowledge_manager
        self._query_count = 0
        self._query_running = False
        self._cancellation_token = None
        self._history: list[str] = []
        self._last_followups: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="main-container"):
            with Horizontal(id="top-row"):
                yield SourcePanel(
                    self._source_registry.list_sources(),
                    id="source-panel",
                )
                yield PipelineBar(id="pipeline-panel")
            yield RichLog(highlight=True, markup=True, id="result-log")
            yield RichLog(highlight=False, markup=True, max_lines=100, id="event-log")
        yield Input(placeholder="Type a question, number for suggestion, or /help", id="query-input")
        yield Static("Ready", id="stats-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "mcpdb"
        self.sub_title = "Interactive Analysis"
        sources = self._source_registry.list_sources()
        if sources:
            self.sub_title = f"{len(sources)} source(s) connected"

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.ERROR:
            self._query_running = False
            error = event.worker.error
            self._log_event(f"[red]Worker error: {error}[/red]")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        user_input = event.value.strip()
        event.input.value = ""

        if not user_input:
            return

        # Follow-up selection by number
        if user_input.isdigit():
            idx = int(user_input) - 1
            if 0 <= idx < len(self._last_followups):
                user_input = self._last_followups[idx]
                self._log_event(f"→ {user_input}")
            else:
                self._log_event("[red]Invalid suggestion number[/red]")
                return

        # Handle slash commands
        if user_input.startswith("/"):
            self._handle_command(user_input)
            return

        # Run query
        self._run_query(user_input)

    def _handle_command(self, cmd: str) -> None:
        result_log = self.query_one("#result-log", RichLog)
        parts = cmd.split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if command in ("/quit", "/exit", "/q"):
            self.exit()
        elif command == "/help":
            result_log.write("[cyan]/help[/cyan]    Show commands")
            result_log.write("[cyan]/mode[/cyan]    Set mode override")
            result_log.write("[cyan]/source[/cyan]  List sources")
            result_log.write("[cyan]/clear[/cyan]   Clear results")
            result_log.write("[cyan]/quit[/cyan]    Exit")
        elif command == "/mode":
            if arg:
                result_log.write(f"Mode override: [bold]{arg}[/bold]")
            else:
                result_log.write("Usage: /mode <quick|simple|extended|deep|auto>")
        elif command == "/source":
            sources = self._source_registry.list_sources()
            for s in sources:
                result_log.write(f"[green]●[/green] {s.display_name}")
        elif command == "/clear":
            self.action_clear_results()
        else:
            result_log.write(f"[dim]Unknown command: {command}[/dim]")

    @work(thread=False)
    async def _run_query(self, question: str) -> None:
        """Run a query asynchronously."""
        if self._query_running:
            self._log_event("[yellow]Query already running[/yellow]")
            return

        self._query_running = True
        self._query_count += 1
        start = time.time()

        try:
            result_log = self.query_one("#result-log", RichLog)
            pipeline = self.query_one("#pipeline-panel", PipelineBar)
            stats = self.query_one("#stats-bar", Static)

            pipeline.reset()
            result_log.write(f"\n[bold]Q: {question}[/bold]\n")
            stats.update(f"Running query #{self._query_count}...")

            from mcpdb.agent.callbacks import CallbackManager
            from mcpdb.agent.graph import run_agent

            callbacks = CallbackManager()

            def on_event(event: Any) -> None:
                etype = event.type
                data = event.data

                if etype == "classify/complete":
                    mode = data.get("mode", "")
                    pipeline.set_mode(mode)
                    pipeline.update_phase("classify", "✓", "green", f"→ {mode}")
                    self._log_event(f"Mode: {mode}")
                elif etype == "classify/start":
                    pipeline.update_phase("classify", "●", "bold cyan")
                elif etype == "plan/start":
                    pipeline.update_phase("plan", "●", "bold cyan")
                elif etype == "plan/ready":
                    count = data.get("step_count", 0)
                    pipeline.update_phase("plan", "✓", "green", f"→ {count} steps")
                    self._log_event(f"Plan: {count} steps")
                elif etype == "step/start":
                    num = data.get("step_number", "?")
                    action = data.get("action", "")
                    pipeline.update_phase("execute", "●", "bold cyan")
                    pipeline.set_step_info(f"Step {num} ({action})")
                    self._log_event(f"Step {num}/{data.get('step_number', '?')} ({action})")
                elif etype == "step/complete":
                    num = data.get("step_number", "?")
                    rows = data.get("rows", 0)
                    ms = data.get("time_ms", 0)
                    pipeline.set_step_info(f"Step {num} done ({rows} rows, {ms}ms)")
                elif etype == "synthesize/start":
                    pipeline.update_phase("execute", "✓", "green")
                    pipeline.update_phase("synthesize", "●", "bold cyan")
                elif etype == "synthesize/complete":
                    pipeline.update_phase("synthesize", "✓", "green")
                elif etype == "debug/start":
                    self._log_event("[yellow]Debug: fixing error[/yellow]")
                elif etype == "observer/warning":
                    msg = data.get("message", "")
                    self._log_event(f"[yellow]⚠ {msg}[/yellow]")
                elif etype == "observer/stuck_warning":
                    msg = data.get("message", "This query may take a while")
                    self._log_event(f"[bold yellow]⚠ {msg}[/bold yellow]")

            callbacks.add_listener(on_event)

            # Pause quality worker during user query to avoid LLM contention
            if self._experience is not None:
                self._experience.pause_worker()
            try:
                state = await run_agent(
                    question,
                    self._source_registry,
                    self._llm,
                    callbacks,
                    experience_cache=(
                        self._experience.cache if self._experience else None
                    ),
                    staging_store=(
                        self._experience.staging if self._experience else None
                    ),
                    no_cache=self._no_cache,
                    knowledge_manager=self._knowledge_manager,
                )
            finally:
                if self._experience is not None:
                    self._experience.resume_worker()

            elapsed = time.time() - start
            response = state.get("response") or "No response generated."

            # Render response
            from rich.markdown import Markdown
            result_log.write(Markdown(response))

            # Save charts to files and show paths in TUI log
            from mcpdb.cli.renderer import save_chart_artifact
            for art in state.get("artifacts", []):
                if art.get("type") == "chart":
                    path = save_chart_artifact(art)
                    if path:
                        result_log.write(f"  [bold green]📊 Chart saved:[/bold green] {path}")

            # Follow-ups
            followups = self._generate_followups(question, response, state)
            self._last_followups = followups
            if followups:
                result_log.write("")
                result_log.write("[dim]Suggestions:[/dim]")
                for i, f in enumerate(followups, 1):
                    result_log.write(f"  [cyan]\\[{i}][/cyan] {f}")

            mode = state.get("query_mode", "?")
            usage = state.get("llm_usage", {})
            tok_str = ""
            if usage.get("calls"):
                from mcpdb.cli.progress import fmt_tokens
                total = usage.get("total_tokens", 0)
                tok_str = f" | {usage['calls']} calls, {fmt_tokens(total)} tokens"
            stats.update(
                f"✓ {mode} | {elapsed:.1f}s{tok_str} | Queries: {self._query_count}"
            )
            self._history.append(question)

        except Exception as e:
            elapsed = time.time() - start
            self._log_event(f"[red]Error: {e}[/red]")
            try:
                result_log = self.query_one("#result-log", RichLog)
                result_log.write(f"[red]Error: {e}[/red]")
                stats = self.query_one("#stats-bar", Static)
                stats.update(f"✗ Error ({elapsed:.1f}s)")
            except Exception:
                pass
        finally:
            self._query_running = False

    def _generate_followups(
        self, question: str, response: str, state: dict[str, Any]
    ) -> list[str]:
        followups = []
        q_lower = question.lower()
        if "table" in response.lower() or "|" in response:
            followups.append("Show this as a chart")
        if any(kw in q_lower for kw in ("average", "sum", "count")):
            followups.append("Break this down by year/month")
        if any(kw in q_lower for kw in ("top", "highest")):
            followups.append("Show the bottom/lowest instead")
        return followups[:3]

    def _log_event(self, msg: str) -> None:
        try:
            log = self.query_one("#event-log", RichLog)
            ts = time.strftime("%H:%M:%S")
            log.write(f"[dim]{ts}[/dim] {msg}")
        except Exception:
            pass

    def action_cancel_query(self) -> None:
        if self._query_running and self._cancellation_token:
            self._cancellation_token.cancel()
            self._log_event("[red]Query cancelled[/red]")

    def action_clear_results(self) -> None:
        try:
            self.query_one("#result-log", RichLog).clear()
        except Exception:
            pass


def run_tui(
    registry: Any,
    llm: Any,
    config: Any,
    experience_service: Any | None = None,
    no_cache: bool = False,
    knowledge_manager: Any = None,
) -> None:
    """Launch the TUI application."""
    app = McpdbTUI(
        registry=registry,
        llm=llm,
        config=config,
        experience_service=experience_service,
        no_cache=no_cache,
        knowledge_manager=knowledge_manager,
    )
    app.run()
