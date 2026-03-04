"""PDF export engine — renders HTML to PDF via weasyprint."""

from __future__ import annotations

import logging

from mcpdb.export.html_export import ExportPayload, render_html

logger = logging.getLogger("mcpdb.export.pdf")


def render_pdf(payload: ExportPayload) -> bytes:
    """Render a PDF from the export payload. Requires weasyprint."""
    try:
        from weasyprint import HTML as WeasyprintHTML
    except ImportError:
        raise ImportError(
            "PDF export requires weasyprint. Install with: pip install mcpdb[export]"
        )

    html_content = render_html(payload)
    pdf_bytes = WeasyprintHTML(string=html_content).write_pdf()
    return pdf_bytes


def export_pdf(payload: ExportPayload, output_path: str) -> str:
    """Export payload to a PDF file."""
    pdf_bytes = render_pdf(payload)
    with open(output_path, "wb") as f:
        f.write(pdf_bytes)
    logger.info("PDF exported to %s (%d bytes)", output_path, len(pdf_bytes))
    return output_path
