"""Export MCP tools — export_conversation to HTML/PDF/Jupyter."""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

from mcp.types import TextContent, Tool

from mcpdb.export.html_export import (
    ExportArtifact,
    ExportMessage,
    ExportPayload,
    render_html,
)

logger = logging.getLogger("mcpdb.mcp.tools.export")


def get_export_tools() -> list[Tool]:
    """Return export tool definitions."""
    return [
        Tool(
            name="export_conversation",
            description=(
                "Export the current conversation and artifacts to HTML, PDF, or "
                "Jupyter notebook format. Returns the file path of the exported file."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "enum": ["html", "pdf", "notebook"],
                        "description": "Export format: html, pdf, or notebook",
                    },
                    "title": {
                        "type": "string",
                        "description": "Title for the export (optional)",
                        "default": "MCPDB Analysis",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Output file path (optional, auto-generated if omitted)",
                    },
                    "messages": {
                        "type": "array",
                        "description": "Messages to export (role + content dicts)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "role": {"type": "string"},
                                "content": {"type": "string"},
                            },
                        },
                    },
                    "artifacts": {
                        "type": "array",
                        "description": "Artifacts to include (type, title, data)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string"},
                                "title": {"type": "string"},
                                "data": {},
                            },
                        },
                    },
                },
                "required": ["format"],
            },
        ),
    ]


def handle_export_tool(
    name: str,
    args: dict[str, Any],
) -> list[TextContent]:
    """Handle export tool calls."""
    if name == "export_conversation":
        return _export_conversation(args)
    return [TextContent(type="text", text=f"Unknown export tool: {name}")]


def _export_conversation(args: dict[str, Any]) -> list[TextContent]:
    """Export conversation to the specified format."""
    fmt = args.get("format", "html")
    title = args.get("title", "MCPDB Analysis")
    output_path = args.get("output_path")

    # Build payload
    messages = [
        ExportMessage(role=m.get("role", "user"), content=m.get("content", ""))
        for m in args.get("messages", [])
    ]
    artifacts = [
        ExportArtifact(
            artifact_type=a.get("type", "code"),
            title=a.get("title", ""),
            data=a.get("data"),
            step_number=a.get("step_number", 0),
        )
        for a in args.get("artifacts", [])
    ]

    payload = ExportPayload(title=title, messages=messages, artifacts=artifacts)

    if fmt == "html":
        return _export_html(payload, output_path)
    elif fmt == "pdf":
        return _export_pdf(payload, output_path)
    elif fmt == "notebook":
        return _export_notebook(payload, output_path)
    else:
        return [TextContent(type="text", text=f"Unknown format: {fmt}. Use html, pdf, or notebook.")]


def _export_html(payload: ExportPayload, output_path: str | None) -> list[TextContent]:
    """Export to HTML."""
    html_content = render_html(payload)
    if not output_path:
        output_path = _temp_path("mcpdb_export", ".html")
    with open(output_path, "w") as f:
        f.write(html_content)
    return [TextContent(type="text", text=f"HTML exported to: {output_path}")]


def _export_pdf(payload: ExportPayload, output_path: str | None) -> list[TextContent]:
    """Export to PDF."""
    try:
        from mcpdb.export.pdf_export import export_pdf
    except ImportError:
        return [TextContent(
            type="text",
            text="PDF export requires weasyprint. Install with: pip install mcpdb[export]",
        )]

    if not output_path:
        output_path = _temp_path("mcpdb_export", ".pdf")
    export_pdf(payload, output_path)
    return [TextContent(type="text", text=f"PDF exported to: {output_path}")]


def _export_notebook(payload: ExportPayload, output_path: str | None) -> list[TextContent]:
    """Export to Jupyter notebook."""
    from mcpdb.export.notebook_export import export_notebook

    if not output_path:
        output_path = _temp_path("mcpdb_export", ".ipynb")
    export_notebook(payload, output_path)
    return [TextContent(type="text", text=f"Notebook exported to: {output_path}")]


def _temp_path(prefix: str, suffix: str) -> str:
    """Generate a temporary file path."""
    fd, path = tempfile.mkstemp(prefix=prefix + "_", suffix=suffix)
    os.close(fd)
    return path
