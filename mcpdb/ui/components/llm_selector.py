"""LLM provider selector — dropdown to switch provider/model in the UI."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from mcpdb.ui.state import UIState

logger = logging.getLogger("mcpdb.ui.llm_selector")

# Provider → default models mapping (first entry is the default)
PROVIDER_MODELS: dict[str, list[str]] = {
    "gemini": [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-3.1-pro-preview",
        "gemini-3-flash-preview",
        "gemini-3.1-flash-lite-preview",
    ],
    "openai": [
        "gpt-4.1",
        "gpt-5",
        "gpt-5-mini",
        "gpt-5.2-pro",
        "gpt-5.3-codex",
    ],
    "anthropic": [
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "claude-haiku-4-5-20251001",
    ],
    "ollama": ["llama3.1", "mistral", "codellama"],
}

# Provider → env var for API key
PROVIDER_ENV_KEYS: dict[str, str] = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def create_llm_selector(state: UIState) -> None:
    """Create the LLM provider selector widget."""
    config = state.config
    llm_cfg = config.llm.reasoning

    with ui.expansion("LLM Provider", icon="smart_toy").classes("w-full"):
        provider_select = ui.select(
            options=list(PROVIDER_MODELS.keys()),
            value=llm_cfg.provider,
            label="Provider",
        ).classes("w-full")

        model_select = ui.select(
            options=PROVIDER_MODELS.get(llm_cfg.provider, []),
            value=llm_cfg.model,
            label="Model",
            with_input=True,
        ).classes("w-full")

        # Pre-fill API key from env var if available
        env_key = PROVIDER_ENV_KEYS.get(llm_cfg.provider, "")
        initial_key = llm_cfg.api_key or (os.environ.get(env_key, "") if env_key else "")

        api_key_input = ui.input(
            label="API Key",
            value=initial_key,
            password=True,
            password_toggle_button=True,
        ).classes("w-full")

        ollama_url_input = ui.input(
            label="Ollama Base URL",
            value="http://localhost:11434",
        ).classes("w-full")
        ollama_url_input.set_visibility(llm_cfg.provider == "ollama")

        def on_provider_change(e) -> None:
            provider = e.value
            models = PROVIDER_MODELS.get(provider, [])
            model_select.options = models
            model_select.value = models[0] if models else ""
            model_select.update()

            # Update API key from env
            env_var = PROVIDER_ENV_KEYS.get(provider, "")
            api_key_input.value = os.environ.get(env_var, "") if env_var else ""

            # Show/hide Ollama URL
            ollama_url_input.set_visibility(provider == "ollama")

        provider_select.on_value_change(on_provider_change)

        def save_config() -> None:
            llm_cfg.provider = provider_select.value
            llm_cfg.model = model_select.value
            llm_cfg.api_key = api_key_input.value
            logger.info("LLM config updated: %s/%s", llm_cfg.provider, llm_cfg.model)
            ui.notify(f"LLM set to {llm_cfg.provider}/{llm_cfg.model}", type="positive")

        ui.button("Save", on_click=save_config, icon="save").props("dense size=sm").classes("mt-2")
