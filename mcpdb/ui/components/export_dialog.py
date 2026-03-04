"""Export dialog — format selection and download for conversation export."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nicegui import ui

from mcpdb.export.html_export import (
    ExportArtifact,
    ExportMessage,
    ExportPayload,
    render_html,
)

if TYPE_CHECKING:
    from mcpdb.ui.state import UIState

logger = logging.getLogger("mcpdb.ui.export_dialog")


class ExportDialog:
    """Modal dialog for exporting conversation data."""

    def __init__(self, state: UIState) -> None:
        self._state = state

    def show(self) -> None:
        """Show the export dialog."""
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-md"):
            ui.label("Export Conversation").classes("text-xl font-bold")
            ui.separator()

            # Title
            title_input = ui.input(
                "Title", value="MCPDB Analysis",
            ).classes("w-full")

            ui.separator()

            # Format buttons
            with ui.column().classes("gap-2 w-full"):
                ui.button(
                    "Export as HTML",
                    icon="code",
                    on_click=lambda: self._export("html", title_input.value, dialog),
                    color="blue",
                ).classes("w-full").props("unelevated")

                ui.button(
                    "Export as PDF",
                    icon="picture_as_pdf",
                    on_click=lambda: self._export("pdf", title_input.value, dialog),
                    color="green",
                ).classes("w-full").props("unelevated")

                ui.button(
                    "Export as Notebook",
                    icon="description",
                    on_click=lambda: self._export("notebook", title_input.value, dialog),
                    color="orange",
                ).classes("w-full").props("unelevated")

            ui.separator()
            ui.button("Cancel", on_click=dialog.close).props("flat")

        dialog.open()

    def _export(self, fmt: str, title: str, dialog: ui.dialog) -> None:
        """Perform the export."""
        payload = self._build_payload(title)

        try:
            if fmt == "html":
                content = render_html(payload)
                ui.download(content.encode(), f"{_safe_filename(title)}.html")

            elif fmt == "pdf":
                from mcpdb.export.pdf_export import render_pdf
                pdf_bytes = render_pdf(payload)
                ui.download(pdf_bytes, f"{_safe_filename(title)}.pdf")

            elif fmt == "notebook":
                from mcpdb.export.notebook_export import render_notebook_json
                nb_json = render_notebook_json(payload)
                ui.download(nb_json.encode(), f"{_safe_filename(title)}.ipynb")

            dialog.close()
            ui.notify(f"Exported as {fmt.upper()}", type="positive")

        except ImportError as e:
            ui.notify(str(e), type="warning")
        except Exception as e:
            ui.notify(f"Export failed: {e}", type="negative")
            logger.error("Export failed: %s", e, exc_info=True)

    def _build_payload(self, title: str) -> ExportPayload:
        """Build export payload from current UI state."""
        messages = [
            ExportMessage(role=m.role, content=m.content, timestamp=m.timestamp)
            for m in self._state.messages
        ]
        artifacts = [
            ExportArtifact(
                artifact_type=a.get("type", "code"),
                title=a.get("title", ""),
                data=a.get("data"),
            )
            for a in self._state.artifacts
        ]
        return ExportPayload(title=title, messages=messages, artifacts=artifacts)


def _safe_filename(title: str) -> str:
    """Convert title to a safe filename."""
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    return safe.strip()[:64] or "export"
