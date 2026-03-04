"""Conversation history management — sliding window with summarization."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("mcpdb.conversation")

DEFAULT_WINDOW_SIZE = 50
DEFAULT_SUMMARY_BATCH = 10  # Summarize this many messages at a time


@dataclass
class ConversationMessage:
    """A single message in the conversation."""

    role: str  # "user", "assistant", "system"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class ConversationSummary:
    """A summary of older conversation messages."""

    text: str
    message_count: int
    start_timestamp: float
    end_timestamp: float


class ConversationHistory:
    """Sliding window conversation history with optional LLM summarization.

    Keeps the last `window_size` messages in full. When the window is exceeded,
    older messages are batched and summarized (if an LLM is provided) or simply
    stored as text summaries.
    """

    def __init__(
        self,
        window_size: int = DEFAULT_WINDOW_SIZE,
        summary_batch: int = DEFAULT_SUMMARY_BATCH,
    ) -> None:
        self._messages: list[ConversationMessage] = []
        self._summaries: list[ConversationSummary] = []
        self._window_size = window_size
        self._summary_batch = summary_batch
        self._total_messages = 0

    def add_message(
        self,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a message to the conversation."""
        msg = ConversationMessage(
            role=role,
            content=content,
            metadata=metadata or {},
        )
        self._messages.append(msg)
        self._total_messages += 1

    @property
    def needs_summarization(self) -> bool:
        """True if messages exceed the window and need summarization."""
        return len(self._messages) > self._window_size + self._summary_batch

    def compact(self, llm_summary: str | None = None) -> ConversationSummary | None:
        """Compact oldest messages beyond the window.

        If llm_summary is provided, use it. Otherwise, create a simple concatenation.
        Returns the created summary, or None if no compaction needed.
        """
        if len(self._messages) <= self._window_size:
            return None

        overflow = len(self._messages) - self._window_size
        old_messages = self._messages[:overflow]
        self._messages = self._messages[overflow:]

        if llm_summary:
            summary_text = llm_summary
        else:
            # Simple fallback: concatenate messages
            lines = []
            for msg in old_messages:
                prefix = msg.role.upper()
                # Truncate long messages
                content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                lines.append(f"[{prefix}] {content}")
            summary_text = "\n".join(lines)

        summary = ConversationSummary(
            text=summary_text,
            message_count=len(old_messages),
            start_timestamp=old_messages[0].timestamp,
            end_timestamp=old_messages[-1].timestamp,
        )
        self._summaries.append(summary)
        logger.info(
            "Compacted %d messages into summary (total summaries: %d)",
            len(old_messages),
            len(self._summaries),
        )
        return summary

    def get_messages_for_prompt(self) -> list[dict[str, str]]:
        """Get messages formatted for LLM prompt injection.

        Returns summary context + recent messages.
        """
        result: list[dict[str, str]] = []

        # Add summary context if any
        if self._summaries:
            summary_text = self._build_summary_context()
            result.append({
                "role": "system",
                "content": f"[Conversation history summary]\n{summary_text}",
            })

        # Add recent messages
        for msg in self._messages:
            result.append({
                "role": msg.role,
                "content": msg.content,
            })

        return result

    def get_context_string(self) -> str:
        """Get full conversation context as a string (for agent prompts)."""
        parts = []

        if self._summaries:
            parts.append("## Previous Conversation Summary")
            parts.append(self._build_summary_context())
            parts.append("")

        if self._messages:
            parts.append("## Recent Messages")
            for msg in self._messages[-10:]:  # Last 10 for context
                prefix = msg.role.upper()
                parts.append(f"[{prefix}] {msg.content}")

        return "\n".join(parts) if parts else "No conversation history."

    def _build_summary_context(self) -> str:
        """Build summary text from all summaries."""
        parts = []
        for i, summary in enumerate(self._summaries, 1):
            parts.append(
                f"[Summary {i}: {summary.message_count} messages]\n{summary.text}"
            )
        return "\n\n".join(parts)

    def get_messages_for_summarization(self) -> list[ConversationMessage]:
        """Get the overflow messages that should be summarized."""
        if len(self._messages) <= self._window_size:
            return []
        overflow = len(self._messages) - self._window_size
        return self._messages[:overflow]

    @property
    def message_count(self) -> int:
        """Current messages in the window."""
        return len(self._messages)

    @property
    def total_messages(self) -> int:
        """Total messages ever added."""
        return self._total_messages

    @property
    def summary_count(self) -> int:
        """Number of summaries created."""
        return len(self._summaries)

    @property
    def summarized_message_count(self) -> int:
        """Total messages that have been summarized."""
        return sum(s.message_count for s in self._summaries)

    def clear(self) -> None:
        """Clear all messages and summaries."""
        self._messages.clear()
        self._summaries.clear()
        self._total_messages = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize for inspection/debugging."""
        return {
            "message_count": self.message_count,
            "total_messages": self.total_messages,
            "summary_count": self.summary_count,
            "summarized_message_count": self.summarized_message_count,
            "window_size": self._window_size,
        }
