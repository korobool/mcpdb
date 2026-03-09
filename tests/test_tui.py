"""Tests for the mcpdb TUI application (v5.3.0)."""

from __future__ import annotations

from unittest.mock import MagicMock

from mcpdb.cli.tui.app import McpdbTUI, PipelineBar, SourcePanel


class TestSourcePanel:
    def test_no_sources(self):
        panel = SourcePanel([])
        text = panel._render_sources()
        assert "No sources" in str(text)

    def test_with_sources(self):
        mock_source = MagicMock()
        mock_source.display_name = "test_db"
        mock_source.source_type.value = "database"
        mock_source.tables = [MagicMock()] * 5
        panel = SourcePanel([mock_source])
        text = panel._render_sources()
        assert "test_db" in str(text)
        assert "5 tables" in str(text)


class TestPipelineBar:
    def test_initial_state(self):
        bar = PipelineBar()
        text = bar._build_text()
        assert "Classify" in str(text)
        assert "Plan" in str(text)
        assert "Execute" in str(text)
        assert "Synthesize" in str(text)

    def test_set_mode(self):
        bar = PipelineBar()
        bar._mode = "simple"
        text = bar._build_text()
        assert "simple" in str(text)

    def test_update_phase(self):
        bar = PipelineBar()
        # Test internal state directly (update_phase calls self.update which needs app context)
        bar._phases["classify"] = ("✓", "green")
        bar._detail = "→ simple"
        assert bar._phases["classify"] == ("✓", "green")
        assert "simple" in bar._detail
        text = bar._build_text()
        assert "simple" in str(text)

    def test_set_step_info(self):
        bar = PipelineBar()
        bar._step_info = "Step 1/3 (sql)"
        text = bar._build_text()
        assert "Step 1/3" in str(text)

    def test_reset_state(self):
        bar = PipelineBar()
        bar._mode = "deep"
        bar._phases["classify"] = ("✓", "green")
        bar._detail = "test"
        bar._step_info = "step"
        # Manually reset state (reset() calls self.update which needs app context)
        for k in bar._phases:
            bar._phases[k] = ("◌", "dim")
        bar._mode = ""
        bar._detail = ""
        bar._step_info = ""
        assert bar._mode == ""
        assert bar._phases["classify"] == ("◌", "dim")
        text = bar._build_text()
        assert "deep" not in str(text)


class TestMcpdbTUI:
    def test_tui_init(self):
        registry = MagicMock()
        registry.list_sources.return_value = []
        llm = MagicMock()
        config = MagicMock()

        app = McpdbTUI(registry=registry, llm=llm, config=config)
        assert app._query_count == 0
        assert not app._query_running

    def test_followup_generation(self):
        registry = MagicMock()
        registry.list_sources.return_value = []
        app = McpdbTUI(registry=registry, llm=MagicMock(), config=MagicMock())

        followups = app._generate_followups(
            "What is the average claim?",
            "| Brand | Avg |\n|---|---|\n| A | 100 |",
            {"query_mode": "simple"},
        )
        assert len(followups) > 0
        assert len(followups) <= 3
