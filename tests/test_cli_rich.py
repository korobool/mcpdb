"""Tests for the mcpdb CLI Rich UI components (v5.3.0)."""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

from rich.console import Console
from rich.panel import Panel

from mcpdb.cli.progress import Phase, RichProgress, MODE_COLORS
from mcpdb.cli.renderer import ResultRenderer


@dataclass
class FakeEvent:
    """Fake StreamingEvent for testing."""
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


# --- Phase tests ---

class TestPhase:
    def test_initial_state(self):
        p = Phase("Test")
        assert p.status == Phase.PENDING
        assert p.icon == "◌"
        assert p.style == "dim"
        assert p.elapsed == 0.0
        assert p.detail == ""

    def test_start(self):
        p = Phase("Test")
        p.start()
        assert p.status == Phase.RUNNING
        assert p.icon == "●"
        assert p.start_time is not None
        assert p.elapsed >= 0

    def test_complete_with_detail(self):
        p = Phase("Test")
        p.start()
        p.complete("→ 3 steps")
        assert p.status == Phase.COMPLETE
        assert p.icon == "✓"
        assert p.style == "green"
        assert p.detail == "→ 3 steps"
        assert p.end_time is not None

    def test_complete_without_detail(self):
        p = Phase("Test")
        p.start()
        p.complete()
        assert p.detail == ""

    def test_fail(self):
        p = Phase("Test")
        p.start()
        p.fail("timeout")
        assert p.status == Phase.ERROR
        assert p.icon == "✗"
        assert p.style == "bold red"
        assert p.detail == "timeout"

    def test_skipped(self):
        p = Phase("Test")
        p.status = Phase.SKIPPED
        assert p.icon == "○"
        assert p.style == "dim"

    def test_elapsed_not_started(self):
        p = Phase("Test")
        assert p.elapsed == 0.0

    def test_elapsed_running(self):
        p = Phase("Test")
        p.start_time = time.time() - 2.0
        p.status = Phase.RUNNING
        assert p.elapsed >= 1.9

    def test_elapsed_completed(self):
        p = Phase("Test")
        p.start_time = time.time() - 5.0
        p.end_time = time.time() - 3.0
        assert 1.5 < p.elapsed < 2.5


# --- RichProgress event handling tests ---

class TestRichProgressEvents:
    def _make(self, question: str = "test question") -> RichProgress:
        p = RichProgress(question=question)
        p._start_time = time.time()
        return p

    def test_classify_flow(self):
        p = self._make()
        p.on_event(FakeEvent("classify/start"))
        assert p._phases["classify"].status == Phase.RUNNING

        p.on_event(FakeEvent("classify/complete", {"mode": "simple", "reasoning": "test"}))
        assert p._mode == "simple"
        assert p._phases["classify"].status == Phase.COMPLETE
        assert "simple" in p._phases["classify"].detail

    def test_classify_override(self):
        p = self._make()
        p.on_event(FakeEvent("classify/override", {"mode": "extended"}))
        assert p._mode == "extended"
        assert "override" in p._phases["classify"].detail

    def test_plan_flow(self):
        p = self._make()
        p.on_event(FakeEvent("plan/start"))
        assert p._phases["plan"].status == Phase.RUNNING

        p.on_event(FakeEvent("plan/ready", {
            "step_count": 3,
            "steps": [
                {"action": "sql", "description": "Get data"},
                {"action": "python", "description": "Analyze"},
                {"action": "sql", "description": "More data"},
            ],
        }))
        assert p._step_count == 3
        assert p._phases["plan"].status == Phase.COMPLETE
        assert "3 steps" in p._phases["plan"].detail
        assert "sql" in p._phases["plan"].detail

    def test_plan_retry(self):
        p = self._make()
        p.on_event(FakeEvent("plan/start"))
        p.on_event(FakeEvent("plan/retry"))
        assert "retrying" in p._phases["plan"].detail

    def test_plan_error(self):
        p = self._make()
        p.on_event(FakeEvent("plan/start"))
        p.on_event(FakeEvent("plan/error"))
        assert "fallback" in p._phases["plan"].detail

    def test_step_tracking(self):
        p = self._make()
        p._step_count = 2

        p.on_event(FakeEvent("step/start", {
            "step_number": 1, "action": "sql",
            "description": "Query", "code_preview": "SELECT 1",
        }))
        assert p._phases["execute"].status == Phase.RUNNING
        assert p._current_step["number"] == 1
        assert p._current_step["action"] == "sql"

        p.on_event(FakeEvent("step/complete", {
            "step_number": 1, "time_ms": 150, "rows": 42,
        }))
        assert p._steps_done == 1
        assert len(p._step_results) == 1
        assert p._step_results[0]["rows"] == 42
        assert p._step_results[0]["time_ms"] == 150
        assert p._current_step == {}

    def test_step_error_clears_current(self):
        p = self._make()
        p.on_event(FakeEvent("step/start", {"step_number": 1, "action": "sql"}))
        assert p._current_step != {}
        p.on_event(FakeEvent("step/error", {"step_number": 1, "error": "fail"}))
        assert p._current_step == {}

    def test_debug_count(self):
        p = self._make()
        p.on_event(FakeEvent("debug/start"))
        p.on_event(FakeEvent("debug/start"))
        assert p._debug_count == 2

    def test_cache_hit(self):
        p = self._make()
        p.on_event(FakeEvent("experience/cache_hit", {"question": "test"}))
        assert p._cache_hit is True

    def test_quick_mode(self):
        p = self._make()
        p.on_event(FakeEvent("quick/start"))
        assert p._phases["plan"].status == Phase.SKIPPED
        assert p._phases["execute"].status == Phase.SKIPPED
        assert p._phases["synthesize"].status == Phase.RUNNING

        p.on_event(FakeEvent("quick/complete"))
        assert p._phases["synthesize"].status == Phase.COMPLETE

    def test_quick_escalate(self):
        p = self._make()
        p.on_event(FakeEvent("quick/start"))
        p.on_event(FakeEvent("quick/escalate"))
        assert p._phases["plan"].status == Phase.PENDING
        assert p._phases["execute"].status == Phase.PENDING
        assert p._phases["synthesize"].status == Phase.PENDING

    def test_extended_mode_adds_phases(self):
        p = self._make()
        p.on_event(FakeEvent("classify/complete", {"mode": "extended"}))
        assert "checkpoint" in p._phases
        assert "validate" in p._phases
        # Verify they're before synthesize in order
        synth_idx = p._phase_order.index("synthesize")
        assert p._phase_order.index("checkpoint") < synth_idx
        assert p._phase_order.index("validate") < synth_idx

    def test_deep_mode_adds_phases(self):
        p = self._make()
        p.on_event(FakeEvent("classify/complete", {"mode": "deep"}))
        assert "blueprint" in p._phases
        assert "investigate" in p._phases
        assert "reason" in p._phases

    def test_deep_blueprint(self):
        p = self._make()
        p.on_event(FakeEvent("classify/complete", {"mode": "deep"}))
        p.on_event(FakeEvent("deep/blueprint", {"investigation_count": 3}))
        assert p._phases["blueprint"].status == Phase.COMPLETE
        assert "3 investigations" in p._phases["blueprint"].detail

    def test_observer_warning(self):
        p = self._make()
        p.on_event(FakeEvent("observer/warning", {"message": "slow plan phase"}))
        assert len(p._warnings) == 1
        assert "slow plan" in p._warnings[0]

    def test_replan(self):
        p = self._make()
        p._step_count = 2
        p._steps_done = 2
        p.on_event(FakeEvent("replan/start"))
        assert p._phases["plan"].status == Phase.RUNNING
        p.on_event(FakeEvent("replan/ready", {"step_count": 3}))
        assert p._step_count == 3
        assert p._steps_done == 0
        assert "replanned" in p._phases["plan"].detail

    def test_revise(self):
        p = self._make()
        p._steps_done = 2
        p.on_event(FakeEvent("revise/ready", {"new_step_count": 3}))
        assert p._step_count == 5  # 2 done + 3 new

    def test_synthesize_completes_execute(self):
        p = self._make()
        p._phases["execute"].start()
        p._steps_done = 3
        p.on_event(FakeEvent("synthesize/start"))
        assert p._phases["execute"].status == Phase.COMPLETE
        assert p._phases["synthesize"].status == Phase.RUNNING

    def test_agent_complete_finishes_running(self):
        p = self._make()
        p._phases["synthesize"].start()
        p.on_event(FakeEvent("agent/complete"))
        assert p._phases["synthesize"].status == Phase.COMPLETE

    def test_checkpoint_validation(self):
        p = self._make()
        p.on_event(FakeEvent("classify/complete", {"mode": "extended"}))
        p.on_event(FakeEvent("checkpoint/start"))
        assert p._phases["checkpoint"].status == Phase.RUNNING
        p.on_event(FakeEvent("checkpoint/complete", {"action": "continue"}))
        assert p._phases["checkpoint"].status == Phase.COMPLETE

        p.on_event(FakeEvent("validate/start"))
        assert p._phases["validate"].status == Phase.RUNNING
        p.on_event(FakeEvent("validate/adequate"))
        assert "adequate" in p._phases["validate"].detail

    def test_build_display(self):
        p = self._make()
        p.on_event(FakeEvent("classify/complete", {"mode": "simple"}))
        p.on_event(FakeEvent("plan/ready", {"step_count": 2, "steps": []}))
        p.on_event(FakeEvent("step/start", {"step_number": 1, "action": "sql"}))

        display = p._build_display()
        assert isinstance(display, Panel)

    def test_build_display_with_step_results(self):
        p = self._make()
        p._step_results = [
            {"number": 1, "time_ms": 100, "rows": 10},
            {"number": 2, "time_ms": 200, "rows": 0},
        ]
        display = p._build_display()
        assert isinstance(display, Panel)

    def test_build_display_long_question_truncated(self):
        long_q = "A" * 200
        p = RichProgress(question=long_q)
        p._start_time = time.time()
        display = p._build_display()
        assert isinstance(display, Panel)

    def test_finish_without_live(self):
        p = self._make()
        p._mode = "simple"
        p._steps_done = 3
        p.finish()  # Should not raise

    def test_error_without_live(self):
        p = self._make()
        p.error("test error")  # Should not raise

    def test_finish_stops_live(self):
        p = self._make()
        p._live = MagicMock()
        p.finish()
        p._live_stopped = True  # Live was stopped
        assert p._live is None


# --- ResultRenderer tests ---

class TestResultRenderer:
    def _make_console(self) -> Console:
        return Console(file=io.StringIO(), force_terminal=True, highlight=False)

    def test_render_empty_response(self):
        c = self._make_console()
        r = ResultRenderer(c)
        r.render_response("")
        output = c.file.getvalue()
        assert "No response generated" in output

    def test_render_response_markdown(self):
        c = self._make_console()
        r = ResultRenderer(c)
        r.render_response("**Hello** world")
        output = c.file.getvalue()
        assert "Hello" in output

    def test_render_with_followups(self):
        c = self._make_console()
        r = ResultRenderer(c)
        r.render_response("Result here", ["Follow 1", "Follow 2"])
        output = c.file.getvalue()
        assert "Follow 1" in output
        assert "Follow 2" in output
        assert "[1]" in output
        assert "[2]" in output

    def test_render_followups_standalone(self):
        c = self._make_console()
        r = ResultRenderer(c)
        r.render_followups(["Q1", "Q2", "Q3"])
        output = c.file.getvalue()
        assert "Suggestions" in output
        assert "Q1" in output

    def test_render_error(self):
        c = self._make_console()
        r = ResultRenderer(c)
        r.render_error("Bad query", "SQL syntax error")
        output = c.file.getvalue()
        assert "Bad query" in output

    def test_render_table_artifact(self):
        c = self._make_console()
        r = ResultRenderer(c)
        r.render_artifacts([{
            "type": "table",
            "columns": ["name", "value"],
            "rows": [["alice", 100], ["bob", 200]],
        }])
        output = c.file.getvalue()
        assert "alice" in output
        assert "bob" in output

    def test_render_empty_artifact(self):
        c = self._make_console()
        r = ResultRenderer(c)
        r.render_artifacts([{"type": "table", "columns": [], "rows": []}])
        # Should not raise or output anything

    def test_render_large_table_truncates(self):
        c = self._make_console()
        r = ResultRenderer(c)
        rows = [[f"item_{i}", i] for i in range(50)]
        r.render_artifacts([{
            "type": "table",
            "columns": ["name", "value"],
            "rows": rows,
        }])
        output = c.file.getvalue()
        assert "..." in output  # Truncation indicator

    def test_render_chart_artifact_empty(self):
        c = self._make_console()
        r = ResultRenderer(c)
        r.render_artifacts([{"type": "chart"}])
        output = c.file.getvalue()
        assert "empty" in output.lower()

    def test_render_chart_artifact_saves_file(self, tmp_path, monkeypatch):
        import mcpdb.cli.renderer as renderer_mod
        monkeypatch.setattr(renderer_mod, "_CHART_DIR", tmp_path)
        c = self._make_console()
        r = ResultRenderer(c)
        import base64
        b64 = base64.b64encode(b"\x89PNG fake image data").decode()
        r.render_artifacts([{
            "type": "chart",
            "title": "Test Chart",
            "data": {"image_base64": b64, "format": "png"},
        }])
        output = c.file.getvalue()
        assert "chart saved" in output.lower()
        # Verify file was written
        files = list(tmp_path.glob("*.png"))
        assert len(files) == 1
        assert "Test_Chart" in files[0].name

    def test_save_chart_artifact_function(self, tmp_path, monkeypatch):
        import mcpdb.cli.renderer as renderer_mod
        from mcpdb.cli.renderer import save_chart_artifact
        monkeypatch.setattr(renderer_mod, "_CHART_DIR", tmp_path)
        import base64
        b64 = base64.b64encode(b"test data").decode()
        path = save_chart_artifact({
            "type": "chart",
            "title": "my chart",
            "data": {"image_base64": b64, "format": "png"},
        })
        assert path is not None
        assert path.exists()
        assert path.read_bytes() == b"test data"

    def test_save_chart_artifact_empty(self):
        from mcpdb.cli.renderer import save_chart_artifact
        assert save_chart_artifact({"type": "chart"}) is None
        assert save_chart_artifact({"type": "chart", "data": {}}) is None


# --- MODE_COLORS ---

class TestModeColors:
    def test_all_modes_have_colors(self):
        for mode in ("quick", "simple", "extended", "optimization_required", "deep"):
            assert mode in MODE_COLORS


# --- Repl tests ---

class TestRepl:
    def test_command_help(self):
        from mcpdb.cli.repl import Repl

        registry = MagicMock()
        registry.list_sources.return_value = []
        repl = Repl(registry=registry, llm=MagicMock(), config=MagicMock())
        repl._console = Console(file=io.StringIO(), force_terminal=True, highlight=False)
        repl._handle_command("/help")
        output = repl._console.file.getvalue()
        assert "/mode" in output
        assert "/schema" in output

    def test_command_mode(self):
        from mcpdb.cli.repl import Repl

        registry = MagicMock()
        registry.list_sources.return_value = []
        repl = Repl(registry=registry, llm=MagicMock(), config=MagicMock())
        repl._console = Console(file=io.StringIO(), force_terminal=True, highlight=False)

        repl._handle_command("/mode simple")
        assert repl._mode_override == "simple"

        repl._handle_command("/mode auto")
        assert repl._mode_override is None

    def test_command_mode_no_arg(self):
        from mcpdb.cli.repl import Repl

        registry = MagicMock()
        registry.list_sources.return_value = []
        repl = Repl(registry=registry, llm=MagicMock(), config=MagicMock())
        repl._console = Console(file=io.StringIO(), force_terminal=True, highlight=False)

        repl._handle_command("/mode")
        output = repl._console.file.getvalue()
        assert "auto" in output

    def test_command_history_empty(self):
        from mcpdb.cli.repl import Repl

        registry = MagicMock()
        registry.list_sources.return_value = []
        repl = Repl(registry=registry, llm=MagicMock(), config=MagicMock())
        repl._console = Console(file=io.StringIO(), force_terminal=True, highlight=False)
        repl._handle_command("/history")
        output = repl._console.file.getvalue()
        assert "No queries" in output

    def test_command_history_with_entries(self):
        from mcpdb.cli.repl import Repl

        registry = MagicMock()
        registry.list_sources.return_value = []
        repl = Repl(registry=registry, llm=MagicMock(), config=MagicMock())
        repl._console = Console(file=io.StringIO(), force_terminal=True, highlight=False)
        repl._history = [
            {"question": "test q", "mode": "simple", "elapsed": 5.0, "response": "r"},
        ]
        repl._handle_command("/history")
        output = repl._console.file.getvalue()
        assert "test q" in output

    def test_command_source(self):
        from mcpdb.cli.repl import Repl
        from mcpdb.sources.base import SourceMetadata, SourceType

        meta = SourceMetadata(
            source_id="test",
            source_type=SourceType.DATABASE,
            display_name="test_db",
            tables=[],
            capabilities=set(),
        )
        registry = MagicMock()
        registry.list_sources.return_value = [meta]
        repl = Repl(registry=registry, llm=MagicMock(), config=MagicMock())
        repl._console = Console(file=io.StringIO(), force_terminal=True, highlight=False)
        repl._handle_command("/source list")
        output = repl._console.file.getvalue()
        assert "test_db" in output

    def test_command_export_no_result(self):
        from mcpdb.cli.repl import Repl

        registry = MagicMock()
        registry.list_sources.return_value = []
        repl = Repl(registry=registry, llm=MagicMock(), config=MagicMock())
        repl._console = Console(file=io.StringIO(), force_terminal=True, highlight=False)
        repl._handle_command("/export")
        output = repl._console.file.getvalue()
        assert "No result" in output

    def test_command_unknown(self):
        from mcpdb.cli.repl import Repl

        registry = MagicMock()
        registry.list_sources.return_value = []
        repl = Repl(registry=registry, llm=MagicMock(), config=MagicMock())
        repl._console = Console(file=io.StringIO(), force_terminal=True, highlight=False)
        repl._handle_command("/foobar")
        output = repl._console.file.getvalue()
        assert "Unknown command" in output

    def test_generate_followups(self):
        from mcpdb.cli.repl import Repl

        registry = MagicMock()
        registry.list_sources.return_value = []
        repl = Repl(registry=registry, llm=MagicMock(), config=MagicMock())

        followups = repl._generate_followups(
            "What is the average claim?",
            "| Brand | Avg |\n|---|---|\n| A | 100 |",
            {"query_mode": "simple"},
        )
        assert len(followups) > 0
        assert len(followups) <= 3

    def test_generate_followups_top(self):
        from mcpdb.cli.repl import Repl

        registry = MagicMock()
        registry.list_sources.return_value = []
        repl = Repl(registry=registry, llm=MagicMock(), config=MagicMock())

        followups = repl._generate_followups(
            "Top 10 customers",
            "result",
            {"query_mode": "simple"},
        )
        assert any("bottom" in f.lower() or "lowest" in f.lower() for f in followups)
