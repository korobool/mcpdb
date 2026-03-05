"""Chat page — main conversation interface."""

from __future__ import annotations

import logging
import re
import time
from typing import Any, TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from mcpdb.ui.state import UIState

logger = logging.getLogger("mcpdb.ui.chat")

# Counter to give each mermaid block a unique id
_mermaid_counter = 0


def _render_mermaid(source: str) -> None:
    """Render a mermaid diagram with explicit JS initialization."""
    global _mermaid_counter
    _mermaid_counter += 1
    div_id = f"mermaid-{_mermaid_counter}-{int(time.time() * 1000)}"

    ui.html(
        f'<div id="{div_id}" class="mermaid-container">{source.strip()}</div>'
    ).classes("w-full overflow-x-auto my-2")

    # Explicitly render this mermaid block after it's in the DOM
    ui.run_javascript(f'''
        (async () => {{
            await new Promise(r => setTimeout(r, 50));
            const el = document.getElementById("{div_id}");
            if (el && typeof mermaid !== "undefined") {{
                try {{
                    const {{ svg }} = await mermaid.render("{div_id}-svg", el.textContent);
                    el.innerHTML = svg;
                }} catch(e) {{
                    console.warn("Mermaid render error:", e);
                    el.innerHTML = "<pre style=\\"color:#f87171\\">" + e.message + "</pre>";
                }}
            }}
        }})();
    ''')


def _render_message_content(content: str, images: list[str] | None = None) -> None:
    """Render a message with markdown, mermaid diagrams, LaTeX, and images."""
    # Split out mermaid code blocks
    parts = re.split(r"```mermaid\s*\n(.*?)```", content, flags=re.DOTALL)

    for i, part in enumerate(parts):
        if i % 2 == 0:
            text = part.strip()
            if text:
                ui.markdown(text).classes("text-sm")
        else:
            _render_mermaid(part)

    # Render attached images
    if images:
        for img_b64 in images:
            src = img_b64 if img_b64.startswith("data:") else f"data:image/png;base64,{img_b64}"
            ui.image(src).classes("max-w-full rounded my-1")

    # Re-render KaTeX for any math in this message
    ui.run_javascript('''
        if (typeof renderMathInElement === "function") {
            renderMathInElement(document.body, {
                delimiters: [
                    {left: "$$", right: "$$", display: true},
                    {left: "$", right: "$", display: false},
                    {left: "\\\\(", right: "\\\\)", display: false},
                    {left: "\\\\[", right: "\\\\]", display: true}
                ],
                throwOnError: false
            });
        }
    ''')


def create_chat_page(state: UIState) -> None:
    """Create the main chat interface.

    Parent (#mcpdb-center) is a flex-column. We create two children:
    - #mcpdb-messages  (flex: 1, scrollable)
    - #mcpdb-input     (flex-shrink: 0, pinned at bottom)
    Both are styled via CSS in app.py so no flex-height-chain issues.
    """
    msg_container = ui.element("div").props('id="mcpdb-messages"')

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
                    f"w-full {'justify-end' if is_user else 'justify-start'} mb-2"
                ):
                    with ui.card().classes(
                        f"max-w-[80%] p-3 {'bg-blue-900' if is_user else 'bg-gray-800'}"
                    ):
                        if is_user:
                            ui.label(msg.content).classes("text-sm")
                        else:
                            images = msg.metadata.get("images")
                            _render_message_content(msg.content, images)

            # Show spinner in chat when processing
            if state.execution.phase != "idle":
                with ui.row().classes("w-full justify-start mb-2"):
                    with ui.card().classes("p-3 bg-gray-800"):
                        with ui.row().classes("items-center gap-2"):
                            ui.spinner("dots", size="sm")
                            phase = state.execution.phase
                            mode = state.execution.mode
                            label = phase.capitalize()
                            if mode:
                                label += f" ({mode})"
                            ui.label(f"{label}...").classes(
                                "text-sm text-gray-400 italic"
                            )

    state.on_update(refresh_messages)
    refresh_messages()

    # Input area — pinned at bottom via CSS
    with ui.element("div").props('id="mcpdb-input"'):
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

        ui.button(icon="send", on_click=send_message).props("round dense")
        text_input.on("keydown.enter.prevent", send_message)


async def _run_query(state: UIState, question: str) -> None:
    """Run the agent and stream updates to the UI."""
    from mcpdb.agent.graph import run_agent
    from mcpdb.agent.callbacks import CallbackManager

    callbacks = CallbackManager()

    def on_event(event: Any) -> None:
        etype = event.type
        data = event.data

        # --- Classification ---
        if etype == "classify/start":
            state.set_phase("classifying")
            state.add_log_entry("Classifying question...")
        elif etype == "classify/complete":
            mode = data.get("mode", "")
            reasoning = data.get("reasoning", "")
            state.set_phase("planning", mode=mode)
            state.execution.classify_reasoning = reasoning
            state.add_log_entry(f"Mode: {mode}" + (f" — {reasoning}" if reasoning else ""))

        # --- Planning ---
        elif etype == "plan/start":
            state.add_log_entry("Generating execution plan...")
        elif etype == "plan/ready":
            count = data.get("step_count", 0)
            state.execution.plan_step_count = count
            state.set_phase("executing")
            state.add_log_entry(f"Plan ready: {count} steps")
        elif etype == "plan/retry":
            attempt = data.get("attempt", 2)
            state.add_log_entry(f"Plan retry (attempt {attempt})...")
        elif etype == "plan/error":
            error = data.get("error", "unknown")
            state.add_log_entry(f"Plan error: {error[:100]}")

        # --- Step execution ---
        elif etype == "step/start":
            from mcpdb.ui.state import ExecutionStep
            state.add_execution_step(ExecutionStep(
                step_number=data.get("step_number", 0),
                action=data.get("action", ""),
                status="running",
            ))
            action = data.get("action", "")
            state.add_log_entry(f"Executing step {data.get('step_number', '?')} ({action})")
        elif etype == "step/complete":
            step_num = data.get("step_number", 0)
            time_ms = data.get("time_ms", 0)
            state.update_step(step_num, status="success", time_ms=time_ms)
            state.add_log_entry(f"Step {step_num} completed ({time_ms:.0f}ms)")
        elif etype == "step/error":
            step_num = data.get("step_number", 0)
            error = data.get("error", "")
            state.update_step(step_num, status="error", error=error)
            state.add_log_entry(f"Step {step_num} failed: {error[:100]}")

        # --- Debug ---
        elif etype == "debug/start":
            attempt = data.get("attempt", 0)
            state.execution.debug_attempts += 1
            state.add_log_entry(f"Debugging step (attempt {attempt})...")
        elif etype == "debug/fixed":
            state.add_log_entry("Debug fix applied, retrying step")
        elif etype == "debug/give_up":
            state.add_log_entry("Debug gave up on step, skipping")
        elif etype == "debug/error":
            state.add_log_entry(f"Debug LLM error: {data.get('error', '')[:80]}")

        # --- Validation ---
        elif etype == "validate/start":
            state.add_log_entry("Validating results...")
        elif etype == "validate/adequate":
            state.execution.validation_status = "adequate"
            state.add_log_entry("Results validated: adequate")
        elif etype == "validate/inadequate":
            reason = data.get("reason", "")
            state.execution.validation_status = "inadequate"
            state.execution.validation_reason = reason
            state.add_log_entry(f"Results inadequate: {reason[:100]}")

        # --- Replan ---
        elif etype == "replan/start":
            state.execution.replan_count += 1
            state.add_log_entry("Replanning...")
        elif etype == "replan/ready":
            count = data.get("step_count", 0)
            state.add_log_entry(f"Replan ready: {count} steps")

        # --- Quick mode ---
        elif etype == "quick/start":
            state.set_phase("executing", mode="quick")
            state.add_log_entry("Quick mode: answering from context")
        elif etype == "quick/escalate":
            reason = data.get("reason", "")
            state.add_log_entry(f"Quick → Simple escalation: {reason}")
        elif etype == "quick/complete":
            state.add_log_entry("Quick mode complete")

        # --- Mode-level events ---
        elif etype == "simple/start":
            state.add_log_entry("Simple mode started")
        elif etype == "simple/complete":
            steps = data.get("steps_executed", 0)
            state.add_log_entry(f"Simple mode complete ({steps} steps executed)")
        elif etype == "extended/start":
            state.add_log_entry("Extended mode started")
        elif etype == "extended/complete":
            steps = data.get("steps_executed", 0)
            state.add_log_entry(f"Extended mode complete ({steps} steps executed)")
        elif etype == "deep/start":
            state.add_log_entry("Deep analysis started")
        elif etype == "deep/complete":
            state.add_log_entry("Deep analysis complete")

        # --- Synthesis ---
        elif etype == "synthesize/start":
            state.set_phase("synthesizing")
            state.add_log_entry("Synthesizing final answer...")
        elif etype == "synthesize/complete":
            state.add_log_entry("Synthesis complete")

        # --- Experience cache ---
        elif etype == "experience/cache_hit":
            state.add_log_entry("Cache hit — using previous result")

        # --- Agent completion ---
        elif etype == "agent/complete":
            mode = data.get("mode", "")
            state.add_log_entry(f"Agent complete (mode: {mode})")

        # --- LLM streaming ---
        elif etype == "llm/token":
            state.set_thinking(data.get("text", ""))
        elif etype == "llm/start":
            state.clear_thinking()
        elif etype == "llm/complete":
            state.clear_thinking()

    callbacks.add_listener(on_event)

    llm = _get_llm(state)

    if llm is None:
        state.add_message(
            "assistant",
            "LLM not configured. Set the appropriate API key environment variable "
            "(GEMINI_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY) "
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

    images: list[str] = []
    for artifact in result.get("artifacts", []):
        if artifact.get("type") == "chart":
            b64 = artifact.get("data", {}).get("image_base64", "")
            if b64:
                images.append(b64)

    state.add_message("assistant", response, images=images)

    for artifact in result.get("artifacts", []):
        state.add_artifact(artifact)


def _get_llm(state: UIState) -> Any:
    """Try to get an LLM provider using config, with env var fallback."""
    from mcpdb.llm.factory import create_provider, _resolve_api_key

    config = state.config
    llm_cfg = config.llm.reasoning

    # Check if an API key is available (factory resolves env vars too)
    api_key = _resolve_api_key(llm_cfg.provider, llm_cfg.api_key)
    if not api_key and llm_cfg.provider != "ollama":
        return None

    try:
        return create_provider(llm_cfg.provider, llm_cfg.model, llm_cfg.api_key)
    except Exception:
        return None
