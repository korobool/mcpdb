"""Async Reasoning Observer — parallel, non-blocking agent execution monitor.

Monitors the agent pipeline via CallbackManager events, detects anomalies
(hangs, loops, disproportionate thinking time), and can intervene via
cooperative cancellation or user notifications.

Design principles:
- Never blocks the main pipeline (runs in a separate asyncio task)
- Event consumption is fire-and-forget (queue overflow → drop, not block)
- Cheap heuristic checks first; LLM assessment only on confirmed anomaly
- Cooperative cancellation via CancellationToken
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from mcpdb.agent.callbacks import CallbackManager, StreamingEvent
from mcpdb.agent.cancellation import CancellationToken

logger = logging.getLogger("mcpdb.agent.observer")


# ---------------------------------------------------------------------------
# Timing expectations per mode (seconds)
# ---------------------------------------------------------------------------

TIMING_EXPECTATIONS: dict[str, dict[str, tuple[float, float]]] = {
    # mode → phase → (expected_max, alert_threshold)
    "quick": {
        "classify": (3, 10),
        "plan": (5, 15),
        "execute": (3, 10),
        "debug": (5, 15),
        "synthesize": (5, 15),
        "total": (15, 45),
    },
    "simple": {
        "classify": (5, 15),
        "plan": (15, 45),
        "execute": (10, 30),
        "debug": (15, 45),
        "synthesize": (10, 30),
        "total": (60, 180),
    },
    "optimization_required": {
        "classify": (5, 15),
        "plan": (20, 60),
        "execute": (15, 45),
        "debug": (20, 60),
        "synthesize": (10, 30),
        "total": (90, 270),
    },
    "extended": {
        "classify": (5, 15),
        "plan": (30, 90),
        "execute": (20, 60),
        "debug": (30, 90),
        "synthesize": (15, 45),
        "total": (300, 600),
    },
    "deep": {
        "classify": (5, 15),
        "plan": (30, 90),
        "execute": (30, 90),
        "debug": (30, 90),
        "synthesize": (20, 60),
        "total": (600, 1200),
    },
}

DEFAULT_TIMING = ("plan", (20, 60))


# ---------------------------------------------------------------------------
# Anomaly types
# ---------------------------------------------------------------------------

@dataclass
class Anomaly:
    """A detected anomaly during agent execution."""
    anomaly_type: str  # timing_warning, timing_critical, debug_loop, empty_loop, stuck
    phase: str
    message: str
    severity: str  # warning, critical
    timestamp: float = field(default_factory=time.time)
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ObserverReport — post-mortem data
# ---------------------------------------------------------------------------

@dataclass
class ObserverReport:
    """Post-mortem report from the observer."""
    question: str
    mode: str
    total_time: float
    phase_times: dict[str, float]
    anomalies: list[Anomaly]
    step_count: int
    debug_count: int
    was_cancelled: bool
    observer_actions: list[str]

    @property
    def had_anomalies(self) -> bool:
        return len(self.anomalies) > 0

    def summary(self) -> str:
        lines = [
            f"Observer Report: {self.question[:80]}",
            f"  Mode: {self.mode} | Total: {self.total_time:.1f}s | Steps: {self.step_count} | Debugs: {self.debug_count}",
        ]
        if self.anomalies:
            lines.append(f"  Anomalies ({len(self.anomalies)}):")
            for a in self.anomalies:
                lines.append(f"    [{a.severity}] {a.anomaly_type}: {a.message}")
        if self.observer_actions:
            lines.append(f"  Actions: {', '.join(self.observer_actions)}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# AsyncReasoningObserver
# ---------------------------------------------------------------------------

class AsyncReasoningObserver:
    """Monitors agent execution in parallel, detects anomalies, can intervene.

    Usage:
        observer = AsyncReasoningObserver(callbacks, cancellation_token)
        observer.start(question="...", mode="simple")
        # ... agent executes ...
        report = observer.stop()
    """

    def __init__(
        self,
        callbacks: CallbackManager,
        cancellation_token: CancellationToken | None = None,
        max_queue_size: int = 1000,
    ) -> None:
        self._callbacks = callbacks
        self._cancel_token = cancellation_token
        self._max_queue_size = max_queue_size

        # State
        self._question = ""
        self._mode = "simple"
        self._start_time = 0.0
        self._phase_starts: dict[str, float] = {}
        self._phase_times: dict[str, float] = {}
        self._current_phase = ""
        self._step_count = 0
        self._debug_count = 0
        self._anomalies: list[Anomaly] = []
        self._actions: list[str] = []
        self._running = False

        # Pattern detection state
        self._recent_errors: list[str] = []
        self._empty_result_count = 0
        self._last_event_time = 0.0

        # Async monitoring
        self._monitor_task: asyncio.Task | None = None
        self._event_queue: asyncio.Queue[StreamingEvent | None] = asyncio.Queue(
            maxsize=max_queue_size,
        )

    def _on_event(self, event: StreamingEvent) -> None:
        """Callback for StreamingEvent — posts to async queue or processes inline."""
        if self._monitor_task is not None:
            # Async mode — post to queue for the monitor loop
            try:
                self._event_queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Drop event rather than block
        else:
            # Sync mode (no event loop) — process inline
            self._process_event(event)

    def start(self, question: str, mode: str = "simple") -> None:
        """Start observing. Call before agent execution begins."""
        self._question = question
        self._mode = mode
        self._start_time = time.time()
        self._phase_starts.clear()
        self._phase_times.clear()
        self._current_phase = ""
        self._step_count = 0
        self._debug_count = 0
        self._anomalies.clear()
        self._actions.clear()
        self._recent_errors.clear()
        self._empty_result_count = 0
        self._last_event_time = time.time()
        self._running = True

        # Register event listener
        self._callbacks.add_listener(self._on_event)

        # Start async monitor task
        try:
            loop = asyncio.get_running_loop()
            self._monitor_task = loop.create_task(self._monitor_loop())
        except RuntimeError:
            # No running loop — observer works in sync-only mode (event processing
            # happens inline via _process_event calls)
            self._monitor_task = None
            logger.debug("No event loop — observer running in sync mode")

    def stop(self) -> ObserverReport:
        """Stop observing and return the report."""
        self._running = False

        # Remove listener
        try:
            self._callbacks.remove_listener(self._on_event)
        except ValueError:
            pass

        # Signal monitor task to stop
        try:
            self._event_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

        # Cancel monitor task if still running
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()

        # Finalize current phase
        if self._current_phase and self._current_phase in self._phase_starts:
            elapsed = time.time() - self._phase_starts[self._current_phase]
            self._phase_times[self._current_phase] = elapsed

        total_time = time.time() - self._start_time

        return ObserverReport(
            question=self._question,
            mode=self._mode,
            total_time=total_time,
            phase_times=dict(self._phase_times),
            anomalies=list(self._anomalies),
            step_count=self._step_count,
            debug_count=self._debug_count,
            was_cancelled=self._cancel_token.is_cancelled if self._cancel_token else False,
            observer_actions=list(self._actions),
        )

    async def _monitor_loop(self) -> None:
        """Async monitoring loop — processes events and checks for anomalies."""
        try:
            while self._running:
                try:
                    event = await asyncio.wait_for(
                        self._event_queue.get(), timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    # Check for stuck phase
                    self._check_stuck()
                    continue

                if event is None:
                    break

                self._process_event(event)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("Observer monitor loop error: %s", e)

    def _process_event(self, event: StreamingEvent) -> None:
        """Process a single event — update state and check for anomalies."""
        self._last_event_time = time.time()
        etype = event.type

        # Phase tracking
        if etype.endswith("/start"):
            phase = etype.rsplit("/", 1)[0]
            self._start_phase(phase)

        elif etype.endswith("/done") or etype.endswith("/complete") or etype.endswith("/ready"):
            phase = etype.rsplit("/", 1)[0]
            self._end_phase(phase)

        # Step counting
        if etype == "step/start":
            self._step_count += 1

        # Debug counting and error tracking
        if etype == "debug/start":
            self._debug_count += 1
            error_msg = event.data.get("error", "")
            if error_msg:
                self._recent_errors.append(str(error_msg)[:200])
                self._check_debug_loop()

        # Empty result tracking
        if etype in ("step/done", "step/complete"):
            result = event.data.get("result_summary", event.data.get("result_preview", ""))
            rows = event.data.get("rows", -1)
            if rows == 0 or "0 rows" in str(result) or "empty" in str(result).lower():
                self._empty_result_count += 1
                self._check_empty_loop()

        # Mode detection for classify override
        if etype == "classify/done" or etype == "classify/override":
            mode = event.data.get("mode", self._mode)
            self._mode = mode

    def _start_phase(self, phase: str) -> None:
        """Record the start of a phase."""
        # Finalize previous phase
        if self._current_phase and self._current_phase in self._phase_starts:
            self._phase_times[self._current_phase] = (
                time.time() - self._phase_starts[self._current_phase]
            )
        self._current_phase = phase
        self._phase_starts[phase] = time.time()

    def _end_phase(self, phase: str) -> None:
        """Record the end of a phase and check timing."""
        if phase in self._phase_starts:
            elapsed = time.time() - self._phase_starts[phase]
            self._phase_times[phase] = elapsed
            self._check_phase_timing(phase, elapsed)

    def _check_phase_timing(self, phase: str, elapsed: float) -> None:
        """Check if a phase took too long."""
        expectations = TIMING_EXPECTATIONS.get(self._mode, TIMING_EXPECTATIONS["simple"])
        expected_max, alert_threshold = expectations.get(phase, (20, 60))

        if elapsed > alert_threshold:
            anomaly = Anomaly(
                anomaly_type="timing_critical",
                phase=phase,
                message=f"{phase} took {elapsed:.1f}s (alert threshold: {alert_threshold}s)",
                severity="critical",
                details={"elapsed": elapsed, "threshold": alert_threshold, "mode": self._mode},
            )
            self._anomalies.append(anomaly)
            self._actions.append(f"timing_critical:{phase}")
            self._emit_warning(
                f"Phase '{phase}' is taking much longer than expected "
                f"({elapsed:.0f}s vs {expected_max:.0f}s expected for {self._mode} mode)"
            )
            logger.warning("Observer: %s", anomaly.message)

        elif elapsed > expected_max:
            anomaly = Anomaly(
                anomaly_type="timing_warning",
                phase=phase,
                message=f"{phase} took {elapsed:.1f}s (expected max: {expected_max}s)",
                severity="warning",
                details={"elapsed": elapsed, "expected_max": expected_max, "mode": self._mode},
            )
            self._anomalies.append(anomaly)
            logger.info("Observer: %s", anomaly.message)

    def _check_stuck(self) -> None:
        """Check if the pipeline appears stuck (no events for a while)."""
        if not self._running or not self._last_event_time:
            return

        silence = time.time() - self._last_event_time
        expectations = TIMING_EXPECTATIONS.get(self._mode, TIMING_EXPECTATIONS["simple"])
        _, total_threshold = expectations.get("total", (60, 180))

        # Consider stuck if no events for > 60s or > half the total threshold
        stuck_threshold = min(60, total_threshold / 2)
        if silence > stuck_threshold:
            anomaly = Anomaly(
                anomaly_type="stuck",
                phase=self._current_phase or "unknown",
                message=f"No events for {silence:.0f}s (phase: {self._current_phase or 'unknown'})",
                severity="critical",
                details={"silence": silence, "threshold": stuck_threshold},
            )
            self._anomalies.append(anomaly)
            self._actions.append("stuck_detected")
            self._emit_warning(
                f"Pipeline appears stuck — no activity for {silence:.0f}s "
                f"in phase '{self._current_phase or 'unknown'}'"
            )
            logger.warning("Observer: %s", anomaly.message)

    def _check_debug_loop(self) -> None:
        """Check for debug loop (same error repeating)."""
        if len(self._recent_errors) < 2:
            return

        # Check if last 2 errors are similar
        last = self._recent_errors[-1]
        prev = self._recent_errors[-2]

        # Simple similarity: same first 100 chars
        if last[:100] == prev[:100]:
            anomaly = Anomaly(
                anomaly_type="debug_loop",
                phase="debug",
                message=f"Same error repeated {len(self._recent_errors)} times: {last[:100]}",
                severity="critical" if len(self._recent_errors) >= 3 else "warning",
                details={"error_count": len(self._recent_errors), "error": last[:200]},
            )
            self._anomalies.append(anomaly)

            if len(self._recent_errors) >= 3:
                self._actions.append("debug_loop_cancel")
                self._emit_warning(
                    f"Debug loop detected — same error repeated {len(self._recent_errors)} times"
                )
                # After 3+ repeated errors, could cancel, but let the pipeline's
                # own max_retries handle it. Just warn.
                logger.warning("Observer: debug loop detected, %d repeats", len(self._recent_errors))

    def _check_empty_loop(self) -> None:
        """Check for empty result loop (execute keeps returning no data)."""
        if self._empty_result_count >= 3:
            anomaly = Anomaly(
                anomaly_type="empty_loop",
                phase="execute",
                message=f"{self._empty_result_count} consecutive empty results",
                severity="warning",
                details={"count": self._empty_result_count},
            )
            self._anomalies.append(anomaly)
            self._emit_warning(
                f"Multiple empty results ({self._empty_result_count}) — "
                "query may not match available data"
            )

    def _emit_warning(self, message: str) -> None:
        """Emit an observer warning event to the callback system."""
        self._callbacks.emit(
            "observer/warning",
            message=message,
            question=self._question[:80],
            mode=self._mode,
        )

    def request_cancel(self, reason: str) -> None:
        """Request cancellation of the current execution."""
        if self._cancel_token:
            self._cancel_token.cancel()
            self._actions.append(f"cancel_requested:{reason}")
            self._callbacks.emit(
                "observer/cancel",
                reason=reason,
                question=self._question[:80],
            )
            logger.info("Observer requested cancellation: %s", reason)

    def check_total_time(self) -> Anomaly | None:
        """Check if total execution time is anomalous (can be called externally)."""
        elapsed = time.time() - self._start_time
        expectations = TIMING_EXPECTATIONS.get(self._mode, TIMING_EXPECTATIONS["simple"])
        expected_max, alert_threshold = expectations.get("total", (60, 180))

        if elapsed > alert_threshold:
            anomaly = Anomaly(
                anomaly_type="timing_critical",
                phase="total",
                message=f"Total time {elapsed:.1f}s exceeds alert threshold {alert_threshold}s",
                severity="critical",
                details={"elapsed": elapsed, "threshold": alert_threshold},
            )
            self._anomalies.append(anomaly)
            return anomaly
        return None
