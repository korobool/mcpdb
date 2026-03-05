"""Source panel component — connect/manage data sources."""

from __future__ import annotations

import logging
import os
from typing import Any, TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from mcpdb.ui.state import UIState

logger = logging.getLogger("mcpdb.ui.source_panel")


def _build_schema_overview(state: UIState) -> None:
    """Build a schema overview message with mermaid ERD and table list.

    Adds the result as an assistant message to the chat.
    """
    sources = state.registry.list_sources()
    if not sources:
        return

    from mcpdb.sources.base import QueryableSource

    parts: list[str] = []

    for meta in sources:
        source = state.registry.get_source(meta.source_id)
        tables = meta.tables
        if not tables:
            continue

        parts.append(f"## Schema Overview: {meta.display_name}\n")

        # Mermaid ERD
        mermaid_lines = ["```mermaid", "erDiagram"]
        for table in tables:
            # Entity with columns
            mermaid_lines.append(f"    {table.name} {{")
            for col in table.columns[:20]:  # limit columns in diagram for readability
                pk_marker = "PK" if col.name in table.primary_keys else ""
                dtype = col.dtype.split("(")[0].upper() if col.dtype else "TEXT"
                # Mermaid erDiagram only allows simple type names
                safe_dtype = dtype.replace(" ", "_")[:15]
                mermaid_lines.append(f"        {safe_dtype} {col.name} {pk_marker}".rstrip())
            if len(table.columns) > 20:
                mermaid_lines.append(f"        TEXT _plus_{len(table.columns) - 20}_more")
            mermaid_lines.append("    }")

        # Relationships
        rels = []
        if hasattr(source, "get_relationships"):
            rels = source.get_relationships()
        for fk in rels:
            src = fk.get("source_table", "")
            tgt = fk.get("target_table", "")
            if src and tgt:
                mermaid_lines.append(f"    {src} }}o--|| {tgt} : \"FK\"")

        mermaid_lines.append("```")
        parts.append("\n".join(mermaid_lines))

        # Table list with row counts
        parts.append("\n### Tables\n")
        parts.append("| # | Table | Rows | Columns |")
        parts.append("|---|-------|------|---------|")
        for i, table in enumerate(tables, 1):
            row_count = f"{table.row_count:,}" if table.row_count is not None else "?"
            col_count = len(table.columns)
            parts.append(f"| {i} | `{table.name}` | {row_count} | {col_count} |")

        # FK summary if any
        if rels:
            parts.append(f"\n### Foreign Keys ({len(rels)})\n")
            for fk in rels:
                src_cols = ", ".join(fk.get("source_columns", []))
                tgt_cols = ", ".join(fk.get("target_columns", []))
                parts.append(
                    f"- `{fk.get('source_table', '')}.{src_cols}` "
                    f"-> `{fk.get('target_table', '')}.{tgt_cols}`"
                )

    if parts:
        state.add_message("assistant", "\n".join(parts))


def create_source_panel(state: UIState) -> None:
    """Create the source management sidebar panel."""
    with ui.column().classes("w-full gap-2"):
        ui.label("Data Sources").classes("text-lg font-bold")

        # Source list
        source_list = ui.column().classes("w-full gap-1")

        def refresh_sources() -> None:
            source_list.clear()
            sources = state.registry.list_sources()
            if not sources:
                with source_list:
                    ui.label("No sources connected").classes("text-gray-400 text-sm italic")
            else:
                for meta in sources:
                    with source_list:
                        with ui.card().classes("w-full p-2"):
                            with ui.row().classes("items-center justify-between w-full"):
                                with ui.column().classes("gap-0"):
                                    ui.label(meta.display_name).classes("font-medium text-sm")
                                    ui.label(
                                        f"{meta.source_type.value} | {len(meta.tables)} tables"
                                    ).classes("text-xs text-gray-400")
                                ui.button(
                                    icon="close",
                                    on_click=lambda sid=meta.source_id: disconnect_source(sid),
                                ).props("flat dense round size=sm")

        def disconnect_source(source_id: str) -> None:
            try:
                state.registry.remove_source(source_id)
                refresh_sources()
                ui.notify(f"Disconnected: {source_id}", type="info")
            except Exception as e:
                ui.notify(f"Error: {e}", type="negative")

        refresh_sources()

        ui.separator()

        # Connection forms
        ui.label("Connect").classes("text-sm font-bold mt-2")

        with ui.tabs().classes("w-full") as tabs:
            db_tab = ui.tab("Database")
            csv_tab = ui.tab("CSV")
            excel_tab = ui.tab("Excel")

        with ui.tab_panels(tabs).classes("w-full"):
            with ui.tab_panel(db_tab):
                conn_input = ui.input(
                    label="Connection String",
                    placeholder="postgresql://user:pass@host/db",
                    value=os.environ.get("MCPDB_DATABASE_URL", ""),
                ).classes("w-full")
                name_input = ui.input(
                    label="Display Name (optional)",
                ).classes("w-full")

                def connect_db() -> None:
                    cs = conn_input.value
                    if not cs:
                        ui.notify("Enter a connection string", type="warning")
                        return
                    try:
                        from mcpdb.sources.database.source import DatabaseSource
                        source = DatabaseSource(cs, display_name=name_input.value or None)
                        state.registry.add_source(source)
                        refresh_sources()
                        conn_input.value = ""
                        name_input.value = ""
                        ui.notify("Connected!", type="positive")

                        # Auto-generate schema overview
                        _build_schema_overview(state)

                    except Exception as e:
                        ui.notify(f"Connection failed: {e}", type="negative")

                ui.button("Connect", on_click=connect_db).classes("w-full mt-2")

            with ui.tab_panel(csv_tab):
                csv_upload = ui.upload(
                    label="Upload CSV",
                    auto_upload=True,
                    multiple=True,
                ).classes("w-full").props("accept=.csv")

                def load_csv(e: Any) -> None:
                    # NiceGUI upload handling
                    ui.notify("CSV upload support coming soon", type="info")

                csv_upload.on("upload", load_csv)

            with ui.tab_panel(excel_tab):
                excel_upload = ui.upload(
                    label="Upload Excel",
                    auto_upload=True,
                ).classes("w-full").props("accept=.xlsx,.xls")

                def load_excel(e: Any) -> None:
                    ui.notify("Excel upload support coming soon", type="info")

                excel_upload.on("upload", load_excel)

        # Refresh button
        ui.button("Refresh", icon="refresh", on_click=refresh_sources).props(
            "flat dense"
        ).classes("mt-2")
