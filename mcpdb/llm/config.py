"""LLM model configuration and usage tracking."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ModelConfig:
    """LLM configuration for the agent."""

    reasoning_provider: str = "anthropic"
    reasoning_model: str = "claude-sonnet-4-6"
    fast_provider: str = "anthropic"
    fast_model: str = "claude-haiku-4-5-20251001"
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout: int = 120


@dataclass
class TokenUsage:
    """Token counts from a single LLM call."""

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMUsage:
    """Accumulated LLM usage for a single ask_question execution."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    breakdown: list[dict] = field(default_factory=list)

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens

    @property
    def total_output_tokens(self) -> int:
        return self.output_tokens

    def add(self, label: str, usage: TokenUsage, model: str = "") -> None:
        """Record a single LLM call's usage."""
        self.calls += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.breakdown.append({
            "label": label,
            "model": model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        })
