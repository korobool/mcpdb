"""Chat page — main conversation interface."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from mcpdb.ui.state import UIState

logger = logging.getLogger("mcpdb.ui.chat")


def create_chat_page(state: UIState) -> None:
    """Create the main chat interface."""
    # Message container (scrollable)
    msg_container = ui.column().classes(
        "w-full flex-grow overflow-y-auto gap-2 p-4"
    )

    def refresh_messages() -> None:
        msg_container.clear()
        with msg_container:
            if not state.messages:
                with ui.column().classes("items-center justify-center w-full py-12"):
                    ui.icon("chat_bubble_outline").classes("text-4xl text-gray-500")
                    ui.label("Ask a question about your data").classes(
                        "text-gray-400 text-lg"
                    )
                    ui.label("Connect a data source first, then ask away.").classes(
                        "text-gray-500 text-sm"
                    )
                return

            for msg in state.messages:
                is_user = msg.role == "user"
                with ui.row().classes(
                    f"w-full {'justify-end' if is_user else 'justify-start'}"
                ):
                    with ui.card().classes(
                        f"max-w-[80%] p-3 {'bg-blue-900' if is_user else 'bg-gray-800'}"
                    ):
                        if not is_user:
                            ui.markdown(msg.content).classes("text-sm")
                        else:
                            ui.label(msg.content).classes("text-sm")

    state.on_update(refresh_messages)
    refresh_messages()

    # Input area
    with ui.row().classes("w-full items-end gap-2 p-4 border-t border-gray-700"):
        text_input = ui.textarea(
            placeholder="Ask a question about your data...",
        ).classes("flex-grow").props("autogrow rows=1 maxlength=2000")

        async def send_message() -> None:
            question = text_input.value
            if not question or not question.strip():
                return

            text_input.value = ""
            state.add_message("user", question.strip())

            # Check if any sources are connected
            sources = state.registry.list_sources()
            if not sources:
                state.add_message(
                    "assistant",
                    "No data sources connected. Please connect a database, "
                    "CSV, or Excel file first using the panel on the left.",
                )
                return

            # Run the agent
            state.set_phase("classifying")
            try:
                await _run_query(state, question.strip())
            except Exception as e:
                logger.error("Query failed: %s", e, exc_info=True)
                state.add_message("assistant", f"Error: {e}")
            finally:
                state.set_phase("idle")

        send_btn = ui.button(icon="send", on_click=send_message).props("round dense")

        # Bind Enter key
        text_input.on("keydown.enter.prevent", send_message)


async def _run_query(state: UIState, question: str) -> None:
    """Run the agent and stream updates to the UI."""
    from mcpdb.agent.graph import run_agent
    from mcpdb.agent.callbacks import CallbackManager

    callbacks = CallbackManager()

    # Wire callbacks to UI state
    def on_event(event: Any) -> None:
        etype = event.type
        if etype == "classify/complete":
            state.set_phase("planning", mode=event.data.get("mode", ""))
        elif etype == "plan/ready":
            state.set_phase("executing")
        elif etype == "step/start":
            from mcpdb.ui.state import ExecutionStep
            state.add_execution_step(ExecutionStep(
                step_number=event.data.get("step_number", 0),
                action=event.data.get("action", ""),
                status="running",
            ))
        elif etype == "step/complete":
            state.update_step(
                event.data.get("step_number", 0),
                status="success",
                time_ms=event.data.get("time_ms", 0),
            )
        elif etype == "step/error":
            state.update_step(
                event.data.get("step_number", 0),
                status="error",
                error=event.data.get("error", ""),
            )
        elif etype == "synthesize/start":
            state.set_phase("synthesizing")

    callbacks.add_listener(on_event)

    # Get LLM (try to create one, fall back to a simple response)
    llm = _get_llm()

    if llm is None:
        state.add_message(
            "assistant",
            "LLM not configured. Set ANTHROPIC_API_KEY environment variable "
            "or configure the LLM provider in mcpdb.yaml.",
        )
        return

    result = await run_agent(
        question=question,
        registry=state.registry,
        llm=llm,
        callbacks=callbacks,
    )

    response = result.get("response", "No response generated.")
    state.add_message("assistant", response)

    # Add artifacts
    for artifact in result.get("artifacts", []):
        state.add_artifact(artifact)


def _get_llm() -> Any:
    """Try to get an LLM provider."""
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    try:
        from mcpdb.llm.provider import AnthropicProvider, ModelConfig
        return AnthropicProvider(ModelConfig(api_key=api_key))
    except Exception:
        return None
