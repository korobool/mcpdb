"""Tests for the Async Reasoning Observer."""

from __future__ import annotations

import asyncio
import time
import pytest

from mcpdb.agent.callbacks import CallbackManager, StreamingEvent
from mcpdb.agent.cancellation import CancellationToken
from mcpdb.agent.observer import (
    AsyncReasoningObserver,
    Anomaly,
    ObserverReport,
    TIMING_EXPECTATIONS,
)


class TestObserverBasic:
    """Basic observer lifecycle tests."""

    def test_start_stop(self):
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test question", mode="simple")
        report = obs.stop()

        assert isinstance(report, ObserverReport)
        assert report.question == "test question"
        assert report.mode == "simple"
        assert report.total_time >= 0
        assert report.step_count == 0
        assert report.debug_count == 0
        assert not report.was_cancelled
        assert not report.had_anomalies

    def test_report_summary(self):
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="what is the average premium?", mode="quick")
        report = obs.stop()

        s = report.summary()
        assert "what is the average premium?" in s
        assert "quick" in s

    def test_step_counting(self):
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="simple")

        # Simulate step events
        cb.emit("step/start", step_number=1)
        cb.emit("step/done", step_number=1, result_summary="5 rows")
        cb.emit("step/start", step_number=2)
        cb.emit("step/done", step_number=2, result_summary="3 rows")

        report = obs.stop()
        assert report.step_count == 2

    def test_debug_counting(self):
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="simple")

        cb.emit("debug/start", error="syntax error near 'FROM'")
        cb.emit("debug/done", fixed=True)
        cb.emit("debug/start", error="column not found")
        cb.emit("debug/done", fixed=True)

        report = obs.stop()
        assert report.debug_count == 2

    def test_listener_cleanup(self):
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        assert len(cb._listeners) == 0

        obs.start(question="test", mode="simple")
        assert len(cb._listeners) == 1

        obs.stop()
        assert len(cb._listeners) == 0


class TestTimingDetection:
    """Tests for timing anomaly detection."""

    def test_no_anomaly_for_fast_phase(self):
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="simple")

        cb.emit("plan/start")
        # Fast — no anomaly
        cb.emit("plan/done")

        report = obs.stop()
        assert not report.had_anomalies

    def test_timing_warning(self):
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="quick")

        # Manually set phase start time in the past
        obs._phase_starts["plan"] = time.time() - 6  # > 5s expected for quick
        obs._current_phase = "plan"

        # End phase — should detect warning
        obs._end_phase("plan")

        assert any(a.anomaly_type == "timing_warning" for a in obs._anomalies)

    def test_timing_critical(self):
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="quick")

        # Way over threshold
        obs._phase_starts["plan"] = time.time() - 20  # > 15s alert for quick
        obs._current_phase = "plan"
        obs._end_phase("plan")

        assert any(a.anomaly_type == "timing_critical" for a in obs._anomalies)

    def test_total_time_check(self):
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="quick")

        # Simulate long execution
        obs._start_time = time.time() - 50  # > 45s alert for quick total

        anomaly = obs.check_total_time()
        assert anomaly is not None
        assert anomaly.anomaly_type == "timing_critical"
        assert anomaly.phase == "total"


class TestPatternDetection:
    """Tests for failure pattern detection."""

    def test_debug_loop_detection(self):
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="simple")

        # Same error twice
        cb.emit("debug/start", error="column 'foo' not found")
        cb.emit("debug/start", error="column 'foo' not found")

        assert any(a.anomaly_type == "debug_loop" for a in obs._anomalies)

    def test_debug_loop_critical_at_three(self):
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="simple")

        for _ in range(3):
            cb.emit("debug/start", error="same error repeated")

        critical = [
            a for a in obs._anomalies
            if a.anomaly_type == "debug_loop" and a.severity == "critical"
        ]
        assert len(critical) >= 1

    def test_no_debug_loop_for_different_errors(self):
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="simple")

        cb.emit("debug/start", error="column 'foo' not found")
        cb.emit("debug/start", error="syntax error near SELECT")

        # Different errors — should not trigger loop detection
        loops = [a for a in obs._anomalies if a.anomaly_type == "debug_loop"]
        assert len(loops) == 0

    def test_empty_result_loop(self):
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="simple")

        for i in range(3):
            cb.emit("step/complete", result_preview="0 rows returned", rows=0)

        assert any(a.anomaly_type == "empty_loop" for a in obs._anomalies)

    def test_stuck_detection(self):
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="quick")

        # Simulate long silence
        obs._last_event_time = time.time() - 70
        obs._current_phase = "execute"
        obs._check_stuck()

        assert any(a.anomaly_type == "stuck" for a in obs._anomalies)


class TestCancellation:
    """Tests for cooperative cancellation."""

    def test_request_cancel(self):
        cb = CallbackManager()
        token = CancellationToken()
        obs = AsyncReasoningObserver(cb, cancellation_token=token)
        obs.start(question="test", mode="simple")

        assert not token.is_cancelled
        obs.request_cancel("debug loop detected")
        assert token.is_cancelled

        report = obs.stop()
        assert report.was_cancelled
        assert "cancel_requested" in report.observer_actions[0]

    def test_report_not_cancelled_by_default(self):
        cb = CallbackManager()
        token = CancellationToken()
        obs = AsyncReasoningObserver(cb, cancellation_token=token)
        obs.start(question="test", mode="simple")

        report = obs.stop()
        assert not report.was_cancelled


class TestObserverWarningEvents:
    """Tests for observer warning events emitted via callbacks."""

    def test_warning_emitted_on_timing(self):
        cb = CallbackManager()
        warnings = []
        cb.add_listener(lambda e: warnings.append(e) if e.type == "observer/warning" else None)

        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="quick")

        # Trigger timing critical
        obs._phase_starts["plan"] = time.time() - 20
        obs._current_phase = "plan"
        obs._end_phase("plan")

        assert any(w.type == "observer/warning" for w in warnings)

    def test_warning_emitted_on_stuck(self):
        cb = CallbackManager()
        warnings = []
        cb.add_listener(lambda e: warnings.append(e) if e.type == "observer/warning" else None)

        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="quick")

        obs._last_event_time = time.time() - 70
        obs._current_phase = "execute"
        obs._check_stuck()

        assert len(warnings) >= 1


class TestStuckWarningEvents:
    """Tests for observer/stuck_warning events emitted on stuck detection."""

    def test_stuck_warning_event_emitted(self):
        """Stuck detection emits observer/stuck_warning event."""
        cb = CallbackManager()
        stuck_warnings = []
        cb.add_listener(lambda e: stuck_warnings.append(e) if e.type == "observer/stuck_warning" else None)

        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="simple")

        obs._last_event_time = time.time() - 70
        obs._current_phase = "execute"
        obs._check_stuck()

        assert len(stuck_warnings) == 1
        assert "cancel" in stuck_warnings[0].data.get("message", "").lower()
        assert stuck_warnings[0].data.get("phase") == "execute"

    def test_stuck_warning_not_spammed(self):
        """Stuck detection should only emit once per stuck period."""
        cb = CallbackManager()
        stuck_warnings = []
        cb.add_listener(lambda e: stuck_warnings.append(e) if e.type == "observer/stuck_warning" else None)

        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="simple")

        obs._last_event_time = time.time() - 70
        obs._current_phase = "execute"
        obs._check_stuck()
        obs._check_stuck()  # second call should be suppressed

        assert len(stuck_warnings) == 1

    def test_deep_mode_longer_stuck_threshold(self):
        """Deep mode should not trigger stuck at 70s (threshold is 120s)."""
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="deep")

        obs._last_event_time = time.time() - 70  # 70s silence
        obs._current_phase = "execute"
        obs._check_stuck()

        # Should NOT be stuck — deep mode threshold is 120s
        assert not any(a.anomaly_type == "stuck" for a in obs._anomalies)

    def test_deep_mode_stuck_at_threshold(self):
        """Deep mode triggers stuck after 120s."""
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="deep")

        obs._last_event_time = time.time() - 125  # > 120s
        obs._current_phase = "execute"
        obs._check_stuck()

        assert any(a.anomaly_type == "stuck" for a in obs._anomalies)

    def test_sequential_mode_longer_threshold(self):
        """Sequential mode uses 120s threshold like deep."""
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="sequential")

        obs._last_event_time = time.time() - 70
        obs._check_stuck()
        assert not any(a.anomaly_type == "stuck" for a in obs._anomalies)

    def test_extended_mode_90s_threshold(self):
        """Extended mode uses 90s stuck threshold."""
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="extended")

        obs._last_event_time = time.time() - 70
        obs._current_phase = "execute"
        obs._check_stuck()
        assert not any(a.anomaly_type == "stuck" for a in obs._anomalies)

        obs._last_event_time = time.time() - 95  # > 90s
        obs._check_stuck()
        assert any(a.anomaly_type == "stuck" for a in obs._anomalies)


class TestStuckWarningEventData:
    """Tests for stuck_warning event data structure and quick/simple thresholds."""

    def test_stuck_warning_event_data_structure(self):
        """Stuck warning event has correct data fields."""
        cb = CallbackManager()
        events = []
        cb.add_listener(lambda e: events.append(e) if e.type == "observer/stuck_warning" else None)

        obs = AsyncReasoningObserver(cb)
        obs.start(question="test data fields", mode="simple")

        obs._last_event_time = time.time() - 70
        obs._current_phase = "execute"
        obs._check_stuck()

        assert len(events) == 1
        data = events[0].data
        assert "message" in data
        assert "phase" in data
        assert data["phase"] == "execute"
        assert "silence_seconds" in data
        assert isinstance(data["silence_seconds"], int)
        assert data["silence_seconds"] >= 60
        assert "mode" in data
        assert data["mode"] == "simple"

    def test_quick_mode_short_threshold(self):
        """Quick mode stuck threshold is min(60, total_threshold/2) = ~22.5s."""
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="quick")

        # Quick total_threshold=45, so stuck_threshold = min(60, 22.5) = 22.5
        # 15s should NOT trigger
        obs._last_event_time = time.time() - 15
        obs._current_phase = "execute"
        obs._check_stuck()
        assert not any(a.anomaly_type == "stuck" for a in obs._anomalies)

        # 25s SHOULD trigger for quick mode (> 22.5)
        obs._last_event_time = time.time() - 25
        obs._check_stuck()
        assert any(a.anomaly_type == "stuck" for a in obs._anomalies)

    def test_simple_mode_60s_threshold(self):
        """Simple mode stuck threshold is min(60, 180/2) = 60s."""
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="simple")

        # Simple total_threshold=180, so stuck_threshold = min(60, 90) = 60
        obs._last_event_time = time.time() - 50
        obs._current_phase = "plan"
        obs._check_stuck()
        assert not any(a.anomaly_type == "stuck" for a in obs._anomalies)

        obs._last_event_time = time.time() - 65
        obs._check_stuck()
        assert any(a.anomaly_type == "stuck" for a in obs._anomalies)

    def test_optimization_mode_threshold(self):
        """Optimization mode stuck threshold is min(60, 270/2) = 60s."""
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="optimization_required")

        # optimization total_threshold=270, so stuck_threshold = min(60, 135) = 60
        obs._last_event_time = time.time() - 50
        obs._current_phase = "execute"
        obs._check_stuck()
        assert not any(a.anomaly_type == "stuck" for a in obs._anomalies)

        obs._last_event_time = time.time() - 65
        obs._check_stuck()
        assert any(a.anomaly_type == "stuck" for a in obs._anomalies)


class TestAsyncMonitorLoop:
    """Tests for the async monitor loop."""

    @pytest.mark.asyncio
    async def test_async_monitor_processes_events(self):
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="async test", mode="simple")

        # Give the monitor loop time to start
        await asyncio.sleep(0.1)

        # Emit events
        cb.emit("step/start", step_number=1)
        cb.emit("step/done", step_number=1, result_summary="5 rows")

        # Give time to process
        await asyncio.sleep(0.2)

        report = obs.stop()
        assert report.step_count == 1

    @pytest.mark.asyncio
    async def test_async_monitor_stops_cleanly(self):
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="async test", mode="simple")

        await asyncio.sleep(0.1)
        report = obs.stop()

        # Monitor task should be done shortly after stop
        if obs._monitor_task:
            await asyncio.sleep(0.2)
            assert obs._monitor_task.done()

    @pytest.mark.asyncio
    async def test_phase_tracking_in_async(self):
        cb = CallbackManager()
        obs = AsyncReasoningObserver(cb)
        obs.start(question="test", mode="simple")

        await asyncio.sleep(0.05)

        cb.emit("plan/start")
        await asyncio.sleep(0.1)
        cb.emit("plan/done")
        await asyncio.sleep(0.1)

        report = obs.stop()
        assert "plan" in report.phase_times
        assert report.phase_times["plan"] >= 0.05  # at least some time
