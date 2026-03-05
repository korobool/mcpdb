"""Execution monitor — detailed step-by-step progress with activity log."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from mcpdb.ui.state import UIState

logger = logging.getLogger("mcpdb.ui.execution_monitor")

_PHASE_LABELS = {
    "idle": "Ready",
    "classifying": "Classifying question...",
    "planning": "Planning execution...",
    "executing": "Executing steps...",
    "synthesizing": "Synthesizing answer...",
}

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
    ui.label("Execution Monitor").classes("text-lg font-bold")

    container = ui.column().classes("w-full gap-2")

    def refresh() -> None:
        container.clear()
        ex = state.execution

        with container:
            is_active = ex.phase != "idle"

            # Phase indicator — always visible
            with ui.row().classes("items-center gap-2 w-full"):
                if is_active:
                    ui.spinner("dots", size="sm", color="primary")

                icon = _PHASE_ICONS.get(ex.phase, "help")
                ui.icon(icon).classes(
                    f"text-lg {'text-blue-400' if is_active else 'text-gray-500'}"
                )
                label = _PHASE_LABELS.get(ex.phase, ex.phase.capitalize())
                ui.label(label).classes(
                    f"text-sm {'font-bold text-blue-300' if is_active else 'text-gray-400'}"
                )
                if ex.mode:
                    ui.badge(ex.mode, color="blue").props("outline")

            if not is_active and not ex.steps and not ex.log_entries:
                ui.label("Waiting for a query...").classes(
                    "text-xs text-gray-500 italic"
                )
                return

            # Classification reasoning
            if ex.classify_reasoning:
                with ui.row().classes("items-start gap-1 w-full"):
                    ui.icon("psychology").classes("text-xs text-purple-400 mt-0.5")
                    ui.label(ex.classify_reasoning).classes(
                        "text-xs text-purple-300 italic"
                    )

            # Plan info
            if ex.plan_step_count > 0:
                with ui.row().classes("items-center gap-1 w-full"):
                    ui.icon("assignment").classes("text-xs text-cyan-400")
                    ui.label(f"Plan: {ex.plan_step_count} steps").classes(
                        "text-xs text-cyan-300"
                    )

            # Progress bar
            if ex.steps:
                completed = sum(1 for s in ex.steps if s.status in ("success", "error"))
                total = len(ex.steps)
                progress = completed / total if total > 0 else 0
                with ui.row().classes("items-center gap-2 w-full"):
                    ui.linear_progress(value=progress, show_value=False).classes(
                        "flex-grow"
                    )
                    ui.label(f"{completed}/{total}").classes("text-xs text-gray-400")

            # Step list
            for step in ex.steps:
                with ui.row().classes("items-center gap-2 w-full"):
                    if step.status == "running":
                        ui.spinner("dots", size="xs", color="blue")
                    elif step.status == "success":
                        ui.icon("check_circle").classes("text-green-500 text-sm")
                    elif step.status == "error":
                        ui.icon("error").classes("text-red-500 text-sm")
                    else:
                        ui.icon("radio_button_unchecked").classes(
                            "text-gray-500 text-sm"
                        )

                    with ui.column().classes("gap-0 flex-grow min-w-0"):
                        desc = step.description or step.action
                        ui.label(
                            f"Step {step.step_number}: {desc}"
                        ).classes("text-sm truncate")
                        if step.time_ms > 0:
                            ui.label(f"{step.time_ms:.0f}ms").classes(
                                "text-xs text-gray-400"
                            )
                        if step.error:
                            ui.label(step.error[:200]).classes(
                                "text-xs text-red-400 break-all"
                            )

            # Debug/validation/replan status
            if ex.debug_attempts > 0:
                with ui.row().classes("items-center gap-1 w-full"):
                    ui.icon("bug_report").classes("text-xs text-orange-400")
                    ui.label(f"Debug attempts: {ex.debug_attempts}").classes(
                        "text-xs text-orange-300"
                    )

            if ex.validation_status:
                color = "green" if ex.validation_status == "adequate" else "amber"
                icon = "verified" if ex.validation_status == "adequate" else "warning"
                with ui.row().classes("items-center gap-1 w-full"):
                    ui.icon(icon).classes(f"text-xs text-{color}-400")
                    label_text = f"Validation: {ex.validation_status}"
                    if ex.validation_reason:
                        label_text += f" — {ex.validation_reason[:80]}"
                    ui.label(label_text).classes(f"text-xs text-{color}-300")

            if ex.replan_count > 0:
                with ui.row().classes("items-center gap-1 w-full"):
                    ui.icon("replay").classes("text-xs text-yellow-400")
                    ui.label(f"Replanned {ex.replan_count} time(s)").classes(
                        "text-xs text-yellow-300"
                    )

            # Thinking text (streaming LLM tokens)
            if ex.thinking_text:
                with ui.card().classes("w-full p-2 bg-gray-800 mt-1"):
                    with ui.row().classes("items-center gap-1 mb-1"):
                        ui.spinner("dots", size="xs", color="blue")
                        ui.label("Thinking...").classes("text-xs text-gray-400")
                    ui.label(ex.thinking_text[-500:]).classes(
                        "text-xs font-mono whitespace-pre-wrap text-gray-300 break-all"
                    )

            # Activity log — detailed timeline
            if ex.log_entries:
                with ui.expansion("Activity Log", icon="list").classes("w-full mt-2").props("dense default-opened"):
                    for entry in ex.log_entries:
                        with ui.row().classes("items-start gap-1 w-full"):
                            ui.icon("circle").classes("text-[6px] text-gray-500 mt-1.5")
                            ui.label(entry).classes(
                                "text-xs text-gray-400 break-all"
                            )

    state.on_update(refresh)
    refresh()
