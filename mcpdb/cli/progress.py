"""Rich-based progress display for agent execution."""

from __future__ import annotations

import threading
import time
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class Phase:
    """Tracks the state of a single pipeline phase."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"
    SKIPPED = "skipped"

    def __init__(self, name: str) -> None:
        self.name = name
        self.status = self.PENDING
        self.start_time: float | None = None
        self.end_time: float | None = None
        self.detail: str = ""

    def start(self) -> None:
        self.status = self.RUNNING
        self.start_time = time.time()

    def complete(self, detail: str = "") -> None:
        self.status = self.COMPLETE
        self.end_time = time.time()
        if detail:
            self.detail = detail

    def fail(self, detail: str = "") -> None:
        self.status = self.ERROR
        self.end_time = time.time()
        if detail:
            self.detail = detail

    @property
    def elapsed(self) -> float:
        if self.start_time is None:
            return 0.0
        end = self.end_time or time.time()
        return end - self.start_time

    @property
    def icon(self) -> str:
        return {
            self.PENDING: "◌",
            self.RUNNING: "●",
            self.COMPLETE: "✓",
            self.ERROR: "✗",
            self.SKIPPED: "○",
        }[self.status]

    @property
    def style(self) -> str:
        return {
            self.PENDING: "dim",
            self.RUNNING: "bold cyan",
            self.COMPLETE: "green",
            self.ERROR: "bold red",
            self.SKIPPED: "dim",
        }[self.status]


MODE_COLORS = {
    "quick": "green",
    "simple": "blue",
    "extended": "yellow",
    "optimization_required": "magenta",
    "deep": "red",
}


class RichProgress:
    """Rich-based progress display replacing _ConsoleProgress.

    Hooks into the agent callback system (StreamingEvent) and renders
    a live-updating panel with pipeline phases, step progress, and timing.
    """

    def __init__(self, question: str = "", source_name: str = "") -> None:
        self._lock = threading.Lock()
        self._console = Console(stderr=True)
        self._question = question
        self._source_name = source_name
        self._start_time = 0.0

        # Pipeline phases
        self._phases: dict[str, Phase] = {
            "classify": Phase("Classify"),
            "plan": Phase("Plan"),
            "execute": Phase("Execute"),
            "synthesize": Phase("Synthesize"),
        }
        self._phase_order = ["classify", "plan", "execute", "synthesize"]

        # Execution tracking
        self._mode = ""
        self._step_count = 0
        self._steps_done = 0
        self._current_step: dict[str, Any] = {}
        self._step_results: list[dict[str, Any]] = []
        self._debug_count = 0
        self._warnings: list[str] = []
        self._cache_hit = False

        # Live display
        self._live: Live | None = None

    def start(self) -> None:
        """Start the live display."""
        self._start_time = time.time()
        self._live = Live(
            self._build_display(),
            console=self._console,
            refresh_per_second=8,
            transient=True,
        )
        self._live.start()

    def on_event(self, event: Any) -> None:
        """Handle agent streaming events."""
        if self._start_time == 0.0:
            self._start_time = time.time()

        etype = event.type
        data = event.data

        with self._lock:
            self._handle_event(etype, data)
            if self._live:
                self._live.update(self._build_display())

    def _handle_event(self, etype: str, data: dict[str, Any]) -> None:
        """Process a single event (must be called with lock held)."""
        # Classification
        if etype == "classify/start":
            self._phases["classify"].start()
        elif etype == "classify/complete":
            self._mode = data.get("mode", "")
            self._phases["classify"].complete(f"→ {self._mode}")
            # Add extra phases for extended/deep modes
            if self._mode == "extended":
                for extra in ["checkpoint", "validate"]:
                    if extra not in self._phases:
                        self._phases[extra] = Phase(extra.title())
                        self._phase_order.insert(-1, extra)
            elif self._mode == "deep":
                for extra in ["blueprint", "investigate", "reason"]:
                    if extra not in self._phases:
                        self._phases[extra] = Phase(extra.title())
                        self._phase_order.insert(-1, extra)
        elif etype == "classify/override":
            self._mode = data.get("mode", "")
            self._phases["classify"].complete(f"→ {self._mode} (override)")

        # Planning
        elif etype == "plan/start":
            self._phases["plan"].start()
        elif etype == "plan/ready":
            self._step_count = data.get("step_count", 0)
            steps_info = data.get("steps", [])
            actions = [s.get("action", "?") for s in steps_info[:5]]
            detail = f"→ {self._step_count} steps"
            if actions:
                detail += f" ({', '.join(actions)})"
            self._phases["plan"].complete(detail)
        elif etype == "plan/retry":
            self._phases["plan"].detail = "retrying..."
        elif etype == "plan/error":
            self._phases["plan"].detail = "fallback plan"

        # Execution
        elif etype == "step/start":
            if self._phases["execute"].status != Phase.RUNNING:
                self._phases["execute"].start()
            self._current_step = {
                "number": data.get("step_number", "?"),
                "action": data.get("action", ""),
                "description": data.get("description", ""),
                "code": data.get("code_preview", ""),
                "start_time": time.time(),
            }
        elif etype == "step/complete":
            self._steps_done += 1
            result = {
                "number": data.get("step_number", "?"),
                "time_ms": data.get("time_ms", 0),
                "rows": data.get("rows", 0),
                "preview": data.get("result_preview", ""),
            }
            self._step_results.append(result)
            self._current_step = {}
            self._phases["execute"].detail = f"Step {self._steps_done}/{self._step_count}"
        elif etype == "step/error":
            self._current_step = {}

        # Debugging
        elif etype == "debug/start":
            self._debug_count += 1

        # Replan
        elif etype == "replan/start":
            self._phases["plan"].start()
            self._phases["plan"].detail = "replanning..."
        elif etype == "replan/ready":
            self._step_count = data.get("step_count", 0)
            self._steps_done = 0
            self._phases["plan"].complete(f"→ {self._step_count} steps (replanned)")

        # Revision
        elif etype == "revise/ready":
            new = data.get("new_step_count", 0)
            self._step_count = self._steps_done + new
            self._phases["plan"].detail = f"revised, {new} more steps"

        # Checkpoint / validation (extended mode)
        elif etype == "checkpoint/start":
            if "checkpoint" in self._phases:
                self._phases["checkpoint"].start()
        elif etype == "checkpoint/complete":
            if "checkpoint" in self._phases:
                action = data.get("action", "")
                self._phases["checkpoint"].complete(f"→ {action}")
        elif etype == "validate/start":
            if "validate" in self._phases:
                self._phases["validate"].start()
        elif etype == "validate/adequate":
            if "validate" in self._phases:
                self._phases["validate"].complete("→ adequate")
        elif etype == "validate/inadequate":
            if "validate" in self._phases:
                self._phases["validate"].complete("→ inadequate, replanning")

        # Deep mode
        elif etype == "deep/blueprint":
            if "blueprint" in self._phases:
                count = data.get("investigation_count", 0)
                self._phases["blueprint"].complete(f"→ {count} investigations")
        elif etype in ("deep/reasoning", "deep/synthesis_start"):
            if "reason" in self._phases:
                self._phases["reason"].start()
        elif etype == "deep/complete":
            if "reason" in self._phases and self._phases["reason"].status == Phase.RUNNING:
                self._phases["reason"].complete()

        # Synthesis
        elif etype == "synthesize/start":
            if self._phases["execute"].status == Phase.RUNNING:
                self._phases["execute"].complete(f"→ {self._steps_done} steps done")
            self._phases["synthesize"].start()
        elif etype == "synthesize/complete":
            self._phases["synthesize"].complete()

        # Cache
        elif etype == "experience/cache_hit":
            self._cache_hit = True

        # Quick mode
        elif etype == "quick/start":
            self._phases["classify"].complete("→ quick")
            self._phases["plan"].status = Phase.SKIPPED
            self._phases["execute"].status = Phase.SKIPPED
            self._phases["synthesize"].start()
        elif etype == "quick/escalate":
            self._phases["synthesize"].status = Phase.PENDING
            self._phases["plan"].status = Phase.PENDING
            self._phases["execute"].status = Phase.PENDING
        elif etype == "quick/complete":
            self._phases["synthesize"].complete()

        # Observer
        elif etype == "observer/warning":
            warn_msg = data.get("message", "anomaly detected")
            self._warnings.append(warn_msg)

        # Agent complete
        elif etype == "agent/complete":
            for phase in self._phases.values():
                if phase.status == Phase.RUNNING:
                    phase.complete()

    def _build_display(self) -> Panel:
        """Build the Rich renderable for the current state."""
        parts: list[Text | Table] = []

        # Mode badge
        if self._mode:
            color = MODE_COLORS.get(self._mode, "white")
            mode_text = Text()
            mode_text.append("Mode: ", style="dim")
            mode_text.append(self._mode, style=f"bold {color}")
            if self._cache_hit:
                mode_text.append("  (cached)", style="dim green")
            parts.append(mode_text)

        # Pipeline phases
        pipeline = Table(show_header=False, show_edge=False, box=None, padding=(0, 1))
        pipeline.add_column(width=2)   # icon
        pipeline.add_column(width=12)  # phase name
        pipeline.add_column(width=8)   # time
        pipeline.add_column()          # detail

        for key in self._phase_order:
            phase = self._phases[key]
            time_str = f"{phase.elapsed:.1f}s" if phase.start_time else ""

            # For execute phase, show step progress inline
            detail = phase.detail
            if key == "execute" and phase.status == Phase.RUNNING and self._current_step:
                step = self._current_step
                step_elapsed = time.time() - step.get("start_time", time.time())
                detail = (
                    f"Step {step['number']}/{self._step_count or '?'}"
                    f" ({step['action']}) {step_elapsed:.1f}s"
                )

            pipeline.add_row(
                Text(phase.icon, style=phase.style),
                Text(phase.name, style=phase.style),
                Text(time_str, style="dim"),
                Text(detail, style="dim" if phase.status != Phase.RUNNING else ""),
            )

        parts.append(pipeline)

        # Step results (last 3)
        if self._step_results:
            recent = self._step_results[-3:]
            for result in recent:
                rows = result.get("rows", 0)
                ms = result.get("time_ms", 0)
                step_text = Text()
                step_text.append(f"  └─ Step {result['number']}: ", style="dim")
                if rows:
                    step_text.append(f"{rows} rows", style="cyan")
                    step_text.append(f" ({ms}ms)", style="dim")
                else:
                    step_text.append(f"({ms}ms)", style="dim")
                parts.append(step_text)

        # Warnings
        for warn in self._warnings[-2:]:
            parts.append(Text(f"  ⚠ {warn}", style="yellow"))

        # Debug count
        if self._debug_count > 0:
            parts.append(Text(f"  Debug attempts: {self._debug_count}", style="dim yellow"))

        # Timing footer
        elapsed = time.time() - self._start_time if self._start_time else 0
        footer = Text()
        footer.append(f"  Elapsed: {elapsed:.1f}s", style="dim")
        parts.append(footer)

        # Build panel
        title = "mcpdb"
        if self._question:
            q = self._question[:70] + "..." if len(self._question) > 70 else self._question
            title = f"mcpdb — {q}"

        return Panel(
            Group(*parts),
            title=title,
            border_style="blue",
            padding=(0, 1),
        )

    def finish(self, state: dict[str, Any] | None = None) -> None:
        """Stop the live display and show final summary."""
        with self._lock:
            for phase in self._phases.values():
                if phase.status == Phase.RUNNING:
                    phase.complete()

        if self._live:
            self._live.stop()
            self._live = None

        elapsed = time.time() - self._start_time if self._start_time else 0

        # Print summary line
        parts = []
        parts.append("[green]✓[/green] Done")
        if self._mode:
            color = MODE_COLORS.get(self._mode, "white")
            parts.append(f"[{color}]{self._mode}[/{color}]")
        parts.append(f"[dim]{self._steps_done} steps[/dim]")
        if self._debug_count:
            parts.append(f"[yellow]{self._debug_count} debug[/yellow]")
        if self._cache_hit:
            parts.append("[green]cached[/green]")
        parts.append(f"[dim]{elapsed:.1f}s[/dim]")

        self._console.print(" | ".join(parts))

    def error(self, msg: str) -> None:
        """Stop the live display and show error."""
        if self._live:
            self._live.stop()
            self._live = None

        self._console.print(f"[bold red]✗[/bold red] {msg}")
