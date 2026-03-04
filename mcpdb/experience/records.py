"""Experience records — data structures for stored experiences."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CodeStep:
    """A single execution step from a successful query."""

    action_type: str  # "sql", "python", "schema", "sample"
    code: str
    result_preview: str = ""
    time_ms: float = 0.0


@dataclass
class SuccessRecord:
    """A successfully answered question with its execution trace."""

    intent_hash: str
    question: str
    source_fingerprint: str
    schema_hash: str
    query_mode: str
    steps: list[CodeStep]
    response: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "success",
            "intent_hash": self.intent_hash,
            "question": self.question,
            "source_fingerprint": self.source_fingerprint,
            "schema_hash": self.schema_hash,
            "query_mode": self.query_mode,
            "steps": [
                {
                    "action_type": s.action_type,
                    "code": s.code,
                    "result_preview": s.result_preview,
                    "time_ms": s.time_ms,
                }
                for s in self.steps
            ],
            "response": self.response,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SuccessRecord:
        steps = [
            CodeStep(
                action_type=s["action_type"],
                code=s["code"],
                result_preview=s.get("result_preview", ""),
                time_ms=s.get("time_ms", 0.0),
            )
            for s in d.get("steps", [])
        ]
        return cls(
            intent_hash=d["intent_hash"],
            question=d["question"],
            source_fingerprint=d["source_fingerprint"],
            schema_hash=d["schema_hash"],
            query_mode=d["query_mode"],
            steps=steps,
            response=d["response"],
            timestamp=d.get("timestamp", 0.0),
            metadata=d.get("metadata", {}),
        )


@dataclass
class FailureRecord:
    """A failed query attempt for anti-pattern tracking."""

    question: str
    source_fingerprint: str
    error_type: str
    error_message: str
    failed_code: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "failure",
            "question": self.question,
            "source_fingerprint": self.source_fingerprint,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "failed_code": self.failed_code,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FailureRecord:
        return cls(
            question=d["question"],
            source_fingerprint=d["source_fingerprint"],
            error_type=d["error_type"],
            error_message=d["error_message"],
            failed_code=d.get("failed_code", ""),
            timestamp=d.get("timestamp", 0.0),
        )
