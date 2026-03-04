"""Deep Analysis viewer — investigation progress and research report."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from mcpdb.ui.state import UIState

logger = logging.getLogger("mcpdb.ui.deep_analysis")


@dataclass
class InvestigationProgress:
    """Track a single investigation's progress."""

    id: int
    question: str
    status: str = "pending"  # pending, running, complete, skipped
    result: str = ""


@dataclass
class DeepAnalysisState:
    """State for deep analysis tracking."""

    active: bool = False
    goal: str = ""
    investigations: list[InvestigationProgress] = field(default_factory=list)
    reasoning_notes: list[str] = field(default_factory=list)
    report: str = ""


def create_deep_analysis_viewer(state: UIState) -> None:
    """Create the deep analysis progress viewer."""
    da_state = DeepAnalysisState()
    container = ui.column().classes("w-full gap-2")

    def on_event(event: Any) -> None:
        """Handle deep analysis events."""
        etype = getattr(event, "type", "")
        data = getattr(event, "data", {})

        if etype == "deep/start":
            da_state.active = True
            da_state.investigations = []
            da_state.reasoning_notes = []
            da_state.report = ""
            refresh()

        elif etype == "deep/blueprint":
            da_state.goal = data.get("goal", "")
            count = data.get("investigation_count", 0)
            da_state.investigations = [
                InvestigationProgress(id=i + 1, question=f"Investigation {i + 1}")
                for i in range(count)
            ]
            refresh()

        elif etype == "deep/investigation_start":
            inv_id = data.get("investigation_id", 0)
            question = data.get("question", "")
            for inv in da_state.investigations:
                if inv.id == inv_id:
                    inv.status = "running"
                    inv.question = question
                    break
            else:
                da_state.investigations.append(
                    InvestigationProgress(id=inv_id, question=question, status="running")
                )
            refresh()

        elif etype == "deep/investigation_complete":
            inv_id = data.get("investigation_id", 0)
            for inv in da_state.investigations:
                if inv.id == inv_id:
                    inv.status = "complete" if data.get("success") else "error"
                    break
            refresh()

        elif etype == "deep/reasoning":
            sufficient = data.get("sufficient", False)
            da_state.reasoning_notes.append(
                f"Sufficient: {'Yes' if sufficient else 'No'}"
            )
            refresh()

        elif etype == "deep/complete":
            da_state.active = False
            refresh()

    def refresh() -> None:
        container.clear()
        if not da_state.active and not da_state.investigations:
            return

        with container:
            ui.label("Deep Analysis").classes("text-sm font-bold")

            if da_state.goal:
                ui.label(f"Goal: {da_state.goal}").classes("text-xs text-gray-300")

            # Progress
            if da_state.investigations:
                completed = sum(
                    1 for i in da_state.investigations if i.status == "complete"
                )
                total = len(da_state.investigations)
                ui.linear_progress(
                    value=completed / total if total > 0 else 0,
                ).classes("w-full")
                ui.label(f"{completed}/{total} investigations").classes(
                    "text-xs text-gray-400"
                )

            # Investigation list
            for inv in da_state.investigations:
                with ui.row().classes("items-center gap-2 w-full"):
                    if inv.status == "running":
                        ui.spinner(size="sm")
                    elif inv.status == "complete":
                        ui.icon("check_circle").classes("text-green")
                    elif inv.status == "skipped":
                        ui.icon("skip_next").classes("text-gray-500")
                    else:
                        ui.icon("radio_button_unchecked").classes("text-gray-500")

                    ui.label(inv.question).classes("text-xs flex-grow")

            # Reasoning notes
            if da_state.reasoning_notes:
                with ui.expansion("Reasoning", icon="psychology").classes("w-full"):
                    for note in da_state.reasoning_notes:
                        ui.label(note).classes("text-xs text-gray-400")

    # Return the event handler so it can be wired to callbacks
    state._deep_analysis_handler = on_event
    refresh()
