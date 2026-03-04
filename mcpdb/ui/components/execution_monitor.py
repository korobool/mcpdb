"""Execution monitor — step-by-step progress with timing."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from mcpdb.ui.state import UIState

logger = logging.getLogger("mcpdb.ui.execution_monitor")

_PHASE_ICONS = {
    "idle": "hourglass_empty",
    "classifying": "psychology",
    "planning": "assignment",
    "executing": "play_circle",
    "synthesizing": "auto_awesome",
}

_STATUS_COLORS = {
    "pending": "grey",
    "running": "blue",
    "success": "green",
    "error": "red",
}


def create_execution_monitor(state: UIState) -> None:
    """Create the execution monitor panel."""
    container = ui.column().classes("w-full gap-1")

    def refresh() -> None:
        container.clear()
        ex = state.execution

        if ex.phase == "idle" and not ex.steps:
            return

        with container:
            # Phase indicator
            with ui.row().classes("items-center gap-2"):
                icon = _PHASE_ICONS.get(ex.phase, "help")
                ui.icon(icon).classes("text-lg")
                ui.label(ex.phase.capitalize()).classes("font-bold text-sm")
                if ex.mode:
                    ui.badge(ex.mode).props("outline")

            # Progress bar
            if ex.steps:
                completed = sum(1 for s in ex.steps if s.status in ("success", "error"))
                total = len(ex.steps)
                progress = completed / total if total > 0 else 0
                ui.linear_progress(value=progress).classes("w-full")

            # Step list
            for step in ex.steps:
                color = _STATUS_COLORS.get(step.status, "grey")
                with ui.row().classes("items-center gap-2 w-full"):
                    if step.status == "running":
                        ui.spinner(size="sm")
                    else:
                        ui.icon(
                            "check_circle" if step.status == "success"
                            else "error" if step.status == "error"
                            else "radio_button_unchecked"
                        ).classes(f"text-{color}")

                    with ui.column().classes("gap-0 flex-grow"):
                        ui.label(
                            f"Step {step.step_number}: {step.description or step.action}"
                        ).classes("text-sm")
                        if step.time_ms > 0:
                            ui.label(f"{step.time_ms:.0f}ms").classes(
                                "text-xs text-gray-400"
                            )
                        if step.error:
                            ui.label(step.error[:100]).classes(
                                "text-xs text-red-400"
                            )

            # Thinking text (streaming LLM tokens)
            if ex.thinking_text:
                with ui.card().classes("w-full p-2 bg-gray-800"):
                    ui.label("Thinking...").classes("text-xs text-gray-400 mb-1")
                    ui.label(ex.thinking_text[-500:]).classes(
                        "text-sm font-mono whitespace-pre-wrap"
                    )

    state.on_update(refresh)
    refresh()
