"""Tests for v2.5.x — Frontend UI (Basic).

Tests UI state management, theme configuration, and component importability.
NiceGUI visual tests require a running server so we focus on the logic layer.
"""

from __future__ import annotations

import time

import pytest

from mcpdb.ui.state import ChatMessage, ExecutionStatus, ExecutionStep, UIState
from mcpdb.ui.theme import (
    DARK_THEME,
    LIGHT_THEME,
    ThemeColors,
    ThemeConfig,
    get_theme,
)


# ---------------------------------------------------------------------------
# Theme tests
# ---------------------------------------------------------------------------

class TestTheme:
    def test_dark_theme(self):
        theme = get_theme("dark")
        assert theme.name == "dark"
        assert theme.colors.background == "#121212"

    def test_light_theme(self):
        theme = get_theme("light")
        assert theme.name == "light"
        assert theme.colors.background == "#FAFAFA"

    def test_default_is_dark(self):
        theme = get_theme()
        assert theme.name == "dark"

    def test_unknown_is_dark(self):
        theme = get_theme("unknown")
        assert theme.name == "dark"

    def test_colors_attributes(self):
        colors = ThemeColors()
        assert colors.primary
        assert colors.secondary
        assert colors.success
        assert colors.error

    def test_theme_post_init(self):
        theme = ThemeConfig(name="test")
        assert theme.colors is not None


# ---------------------------------------------------------------------------
# ChatMessage tests
# ---------------------------------------------------------------------------

class TestChatMessage:
    def test_basic_message(self):
        msg = ChatMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.timestamp > 0

    def test_metadata(self):
        msg = ChatMessage(role="assistant", content="Hi", metadata={"model": "test"})
        assert msg.metadata["model"] == "test"


# ---------------------------------------------------------------------------
# ExecutionStep tests
# ---------------------------------------------------------------------------

class TestExecutionStep:
    def test_defaults(self):
        step = ExecutionStep(step_number=1, action="sql")
        assert step.status == "pending"
        assert step.time_ms == 0.0
        assert step.error == ""

    def test_attributes(self):
        step = ExecutionStep(
            step_number=2,
            action="python",
            description="Analyze data",
            status="running",
        )
        assert step.step_number == 2
        assert step.action == "python"


class TestExecutionStatus:
    def test_defaults(self):
        status = ExecutionStatus()
        assert status.phase == "idle"
        assert status.mode == ""
        assert status.steps == []


# ---------------------------------------------------------------------------
# UIState tests
# ---------------------------------------------------------------------------

class TestUIState:
    def test_initial_state(self):
        state = UIState()
        assert len(state.messages) == 0
        assert state.execution.phase == "idle"
        assert len(state.artifacts) == 0
        assert state.config is not None
        assert state.config.llm.reasoning.provider == "gemini"

    def test_initial_state_with_config(self):
        from mcpdb.config import McpdbConfig, LLMConfig, LLMModelConfig
        cfg = McpdbConfig(llm=LLMConfig(reasoning=LLMModelConfig(provider="openai", model="gpt-4.1")))
        state = UIState(config=cfg)
        assert state.config.llm.reasoning.provider == "openai"
        assert state.config.llm.reasoning.model == "gpt-4.1"

    def test_add_message(self):
        state = UIState()
        msg = state.add_message("user", "Hello!")
        assert len(state.messages) == 1
        assert msg.role == "user"
        assert msg.content == "Hello!"

    def test_add_multiple_messages(self):
        state = UIState()
        state.add_message("user", "Q1")
        state.add_message("assistant", "A1")
        state.add_message("user", "Q2")
        assert len(state.messages) == 3
        assert state.messages[1].role == "assistant"

    def test_clear_messages(self):
        state = UIState()
        state.add_message("user", "test")
        state.clear_messages()
        assert len(state.messages) == 0

    def test_set_phase(self):
        state = UIState()
        state.set_phase("classifying")
        assert state.execution.phase == "classifying"

    def test_set_phase_with_kwargs(self):
        state = UIState()
        state.set_phase("planning", mode="simple")
        assert state.execution.phase == "planning"
        assert state.execution.mode == "simple"

    def test_set_phase_idle_resets(self):
        state = UIState()
        state.add_execution_step(ExecutionStep(step_number=1, action="sql"))
        state.set_phase("idle")
        assert state.execution.steps == []
        assert state.execution.current_step == 0

    def test_add_execution_step(self):
        state = UIState()
        step = ExecutionStep(step_number=1, action="sql", description="Query")
        state.add_execution_step(step)
        assert len(state.execution.steps) == 1
        assert state.execution.steps[0].action == "sql"

    def test_update_step(self):
        state = UIState()
        state.add_execution_step(ExecutionStep(step_number=1, action="sql"))
        state.update_step(1, status="success", time_ms=42.0)
        assert state.execution.steps[0].status == "success"
        assert state.execution.steps[0].time_ms == 42.0

    def test_update_nonexistent_step(self):
        state = UIState()
        # Should not raise
        state.update_step(99, status="success")

    def test_add_artifact(self):
        state = UIState()
        state.add_artifact({"type": "table", "title": "Results", "data": {}})
        assert len(state.artifacts) == 1

    def test_clear_artifacts(self):
        state = UIState()
        state.add_artifact({"type": "chart"})
        state.clear_artifacts()
        assert len(state.artifacts) == 0

    def test_update_callback(self):
        state = UIState()
        calls = []
        state.on_update(lambda: calls.append(1))
        state.add_message("user", "test")
        assert len(calls) == 1

    def test_multiple_callbacks(self):
        state = UIState()
        calls_a = []
        calls_b = []
        state.on_update(lambda: calls_a.append(1))
        state.on_update(lambda: calls_b.append(1))
        state.add_message("user", "test")
        assert len(calls_a) == 1
        assert len(calls_b) == 1

    def test_callback_error_doesnt_break(self):
        state = UIState()

        def bad_callback() -> None:
            raise ValueError("boom")

        state.on_update(bad_callback)
        # Should not raise
        state.add_message("user", "test")
        assert len(state.messages) == 1

    def test_message_with_metadata(self):
        state = UIState()
        msg = state.add_message("assistant", "Answer", model="test", cached=True)
        assert msg.metadata["model"] == "test"
        assert msg.metadata["cached"] is True


# ---------------------------------------------------------------------------
# Module import tests
# ---------------------------------------------------------------------------

class TestImports:
    def test_import_app(self):
        from mcpdb.ui.app import create_app, run_ui, get_state
        assert callable(create_app)
        assert callable(run_ui)
        assert callable(get_state)

    def test_import_chat(self):
        from mcpdb.ui.pages.chat import create_chat_page
        assert callable(create_chat_page)

    def test_import_source_panel(self):
        from mcpdb.ui.components.source_panel import create_source_panel
        assert callable(create_source_panel)

    def test_import_artifact_viewer(self):
        from mcpdb.ui.components.artifact_viewer import create_artifact_viewer
        assert callable(create_artifact_viewer)

    def test_import_execution_monitor(self):
        from mcpdb.ui.components.execution_monitor import create_execution_monitor
        assert callable(create_execution_monitor)

    def test_import_schema_viewer(self):
        from mcpdb.ui.components.schema_viewer import create_schema_viewer
        assert callable(create_schema_viewer)

    def test_import_excel_viewer(self):
        from mcpdb.ui.components.excel_viewer import create_excel_viewer
        assert callable(create_excel_viewer)

    def test_import_llm_selector(self):
        from mcpdb.ui.components.llm_selector import create_llm_selector, PROVIDER_MODELS
        assert callable(create_llm_selector)
        assert "gemini" in PROVIDER_MODELS
        assert "openai" in PROVIDER_MODELS
        assert "anthropic" in PROVIDER_MODELS
        assert "ollama" in PROVIDER_MODELS

    def test_import_cost_gate_dialog(self):
        from mcpdb.ui.components.cost_gate_dialog import CostGateDialog
        assert callable(CostGateDialog)

    def test_import_deep_analysis_viewer(self):
        from mcpdb.ui.components.deep_analysis_viewer import (
            create_deep_analysis_viewer,
            DeepAnalysisState,
            InvestigationProgress,
        )
        assert callable(create_deep_analysis_viewer)

    def test_get_state_singleton(self):
        from mcpdb.ui.app import get_state
        s1 = get_state()
        s2 = get_state()
        assert s1 is s2


# ---------------------------------------------------------------------------
# Deep Analysis state tests
# ---------------------------------------------------------------------------

class TestDeepAnalysisState:
    def test_defaults(self):
        from mcpdb.ui.components.deep_analysis_viewer import DeepAnalysisState
        state = DeepAnalysisState()
        assert state.active is False
        assert state.goal == ""
        assert state.investigations == []
        assert state.reasoning_notes == []
        assert state.report == ""

    def test_investigation_progress(self):
        from mcpdb.ui.components.deep_analysis_viewer import InvestigationProgress
        inv = InvestigationProgress(id=1, question="What is churn?")
        assert inv.id == 1
        assert inv.status == "pending"
        assert inv.result == ""

    def test_investigation_status_transitions(self):
        from mcpdb.ui.components.deep_analysis_viewer import InvestigationProgress
        inv = InvestigationProgress(id=1, question="Q1")
        inv.status = "running"
        assert inv.status == "running"
        inv.status = "complete"
        assert inv.status == "complete"

    def test_state_with_investigations(self):
        from mcpdb.ui.components.deep_analysis_viewer import (
            DeepAnalysisState,
            InvestigationProgress,
        )
        state = DeepAnalysisState(
            active=True,
            goal="Investigate churn",
            investigations=[
                InvestigationProgress(id=1, question="Q1", status="complete"),
                InvestigationProgress(id=2, question="Q2", status="running"),
                InvestigationProgress(id=3, question="Q3"),
            ],
        )
        assert state.active is True
        assert len(state.investigations) == 3
        assert state.investigations[0].status == "complete"
        assert state.investigations[2].status == "pending"


# ---------------------------------------------------------------------------
# Cost gate dialog tests
# ---------------------------------------------------------------------------

class TestCostGateDialog:
    def test_init(self):
        from mcpdb.ui.components.cost_gate_dialog import CostGateDialog
        dialog = CostGateDialog()
        assert dialog._dialog is None
        assert dialog._callback is None

    def test_select_invokes_callback(self):
        from mcpdb.ui.components.cost_gate_dialog import CostGateDialog
        dialog = CostGateDialog()
        results = []
        dialog._callback = lambda s: results.append(s)
        # _select without a dialog (no UI context)
        dialog._select("SAMPLE")
        assert results == ["SAMPLE"]

    def test_select_strategies(self):
        from mcpdb.ui.components.cost_gate_dialog import CostGateDialog
        dialog = CostGateDialog()
        for strategy in ("SAMPLE", "FULL", "CANCEL"):
            results = []
            dialog._callback = lambda s: results.append(s)
            dialog._select(strategy)
            assert results == [strategy]

    def test_close_no_dialog(self):
        from mcpdb.ui.components.cost_gate_dialog import CostGateDialog
        dialog = CostGateDialog()
        # Should not raise when no dialog is open
        dialog.close()


# ---------------------------------------------------------------------------
# Schema viewer logic tests
# ---------------------------------------------------------------------------

class TestSchemaViewerLogic:
    def test_schema_viewer_function_signature(self):
        import inspect
        from mcpdb.ui.components.schema_viewer import create_schema_viewer
        sig = inspect.signature(create_schema_viewer)
        assert "state" in sig.parameters

    def test_sample_loader_function_exists(self):
        from mcpdb.ui.components.schema_viewer import _load_sample
        assert callable(_load_sample)


# ---------------------------------------------------------------------------
# Excel viewer logic tests
# ---------------------------------------------------------------------------

class TestExcelViewerLogic:
    def test_excel_viewer_function_signature(self):
        import inspect
        from mcpdb.ui.components.excel_viewer import create_excel_viewer
        sig = inspect.signature(create_excel_viewer)
        assert "state" in sig.parameters

    def test_sheet_view_function_exists(self):
        from mcpdb.ui.components.excel_viewer import _create_sheet_view
        assert callable(_create_sheet_view)
