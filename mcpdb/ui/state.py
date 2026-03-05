"""Shared UI state — manages sources, messages, and execution status."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from mcpdb.config import McpdbConfig
from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.ui.state")


@dataclass
class ChatMessage:
    """A single chat message."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionStep:
    """A tracked execution step for the monitor."""

    step_number: int
    action: str
    description: str = ""
    status: str = "pending"  # pending, running, success, error
    time_ms: float = 0.0
    result_preview: str = ""
    error: str = ""


@dataclass
class ExecutionStatus:
    """Current execution state for the monitor."""

    phase: str = "idle"  # idle, classifying, planning, executing, synthesizing
    mode: str = ""
    steps: list[ExecutionStep] = field(default_factory=list)
    current_step: int = 0
    started_at: float = 0.0
    thinking_text: str = ""
    # Extended tracking
    classify_reasoning: str = ""
    plan_analysis: str = ""
    plan_approach: str = ""
    plan_step_count: int = 0
    debug_attempts: int = 0
    validation_status: str = ""  # adequate, inadequate, ""
    validation_reason: str = ""
    replan_count: int = 0
    log_entries: list[str] = field(default_factory=list)  # ordered activity log


class UIState:
    """Global UI state shared across all components."""

    def __init__(self, config: McpdbConfig | None = None) -> None:
        self.config = config or McpdbConfig()
        self.registry = SourceRegistry()
        self.messages: list[ChatMessage] = []
        self.execution = ExecutionStatus()
        self.artifacts: list[dict[str, Any]] = []
        self._update_callbacks: list[Any] = []

    def add_message(self, role: str, content: str, **metadata: Any) -> ChatMessage:
        """Add a chat message and notify UI."""
        msg = ChatMessage(role=role, content=content, metadata=metadata)
        self.messages.append(msg)
        self._notify()
        return msg

    def clear_messages(self) -> None:
        """Clear chat history."""
        self.messages.clear()
        self._notify()

    def set_phase(self, phase: str, **kwargs: Any) -> None:
        """Update execution phase."""
        self.execution.phase = phase
        if phase == "idle":
            self.execution.steps = []
            self.execution.current_step = 0
            self.execution.classify_reasoning = ""
            self.execution.plan_analysis = ""
            self.execution.plan_approach = ""
            self.execution.plan_step_count = 0
            self.execution.debug_attempts = 0
            self.execution.validation_status = ""
            self.execution.validation_reason = ""
            self.execution.replan_count = 0
            self.execution.log_entries = []
        for k, v in kwargs.items():
            if hasattr(self.execution, k):
                setattr(self.execution, k, v)
        self._notify()

    def add_execution_step(self, step: ExecutionStep) -> None:
        """Add a step to the execution monitor."""
        self.execution.steps.append(step)
        self._notify()

    def update_step(self, step_number: int, **kwargs: Any) -> None:
        """Update an execution step."""
        for step in self.execution.steps:
            if step.step_number == step_number:
                for k, v in kwargs.items():
                    if hasattr(step, k):
                        setattr(step, k, v)
                break
        self._notify()

    def set_thinking(self, text: str) -> None:
        """Append streaming LLM token to thinking text."""
        self.execution.thinking_text += text
        self._notify()

    def clear_thinking(self) -> None:
        """Clear the thinking text."""
        self.execution.thinking_text = ""
        self._notify()

    def add_log_entry(self, entry: str) -> None:
        """Add an entry to the activity log."""
        self.execution.log_entries.append(entry)
        self._notify()

    def add_artifact(self, artifact: dict[str, Any]) -> None:
        """Add a result artifact (table, chart)."""
        self.artifacts.append(artifact)
        self._notify()

    def clear_artifacts(self) -> None:
        """Clear artifacts."""
        self.artifacts.clear()
        self._notify()

    def on_update(self, callback: Any) -> None:
        """Register an update callback."""
        self._update_callbacks.append(callback)

    def _notify(self) -> None:
        """Notify all registered callbacks."""
        for cb in self._update_callbacks:
            try:
                cb()
            except Exception:
                pass
