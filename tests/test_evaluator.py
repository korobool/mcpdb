"""Tests for quality evaluator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mcpdb.experience.evaluator import QualityEvaluator, _clamp
from mcpdb.experience.records import CodeStep, QualityResult, StagedRecord


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_staged(
    mode: str = "simple",
    steps: list[CodeStep] | None = None,
    response: str = "Here are the top 10 customers by revenue...",
) -> StagedRecord:
    if steps is None:
        steps = [
            CodeStep(
                action_type="sql",
                code="SELECT * FROM customers ORDER BY revenue DESC LIMIT 10",
                result_preview="10 rows returned",
                time_ms=42.0,
            ),
        ]
    return StagedRecord(
        intent_hash="test_hash",
        question="Show top 10 customers",
        source_fingerprint="fp_test",
        schema_hash="sh_test",
        query_mode=mode,
        steps=steps,
        response=response,
        semantic_hash="sem_test",
    )


def _make_mock_llm(score: int = 8, verdict: str = "promote", issues: list | None = None):
    """Create a mock LLM that returns a quality evaluation."""
    llm = MagicMock()
    llm.generate_json = AsyncMock(return_value=(
        {
            "score": score,
            "completeness": score,
            "accuracy": score,
            "relevance": score,
            "clarity": score,
            "issues": issues or [],
            "verdict": verdict,
        },
        {"input_tokens": 100, "output_tokens": 50},
    ))
    return llm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestQualityEvaluator:
    @pytest.mark.asyncio
    async def test_promote_high_score(self):
        evaluator = QualityEvaluator(min_score=7)
        llm = _make_mock_llm(score=8, verdict="promote")
        record = _make_staged()

        result = await evaluator.evaluate(record, llm)

        assert result.score == 8
        assert result.verdict == "promote"
        llm.generate_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_reject_low_score(self):
        evaluator = QualityEvaluator(min_score=7)
        llm = _make_mock_llm(score=4, verdict="reject")
        record = _make_staged()

        result = await evaluator.evaluate(record, llm)

        assert result.score == 4
        assert result.verdict == "reject"

    @pytest.mark.asyncio
    async def test_verdict_overridden_by_threshold(self):
        """Even if LLM says promote, our threshold overrides."""
        evaluator = QualityEvaluator(min_score=7)
        # LLM says promote but score is 5
        llm = _make_mock_llm(score=5, verdict="promote")
        record = _make_staged()

        result = await evaluator.evaluate(record, llm)

        # Our threshold should override: score 5 < min_score 7 → reject
        assert result.verdict == "reject"

    @pytest.mark.asyncio
    async def test_quick_mode_auto_promote(self):
        """Quick mode with no executable steps gets auto-promoted."""
        evaluator = QualityEvaluator(min_score=7)
        llm = _make_mock_llm()  # should NOT be called
        record = _make_staged(mode="quick", steps=[])

        result = await evaluator.evaluate(record, llm)

        assert result.score == 10
        assert result.verdict == "promote"
        llm.generate_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_quick_mode_with_steps_not_auto(self):
        """Quick mode WITH executable steps should still go through LLM."""
        evaluator = QualityEvaluator(min_score=7)
        llm = _make_mock_llm(score=8)
        record = _make_staged(
            mode="quick",
            steps=[CodeStep(action_type="sql", code="SELECT 1")],
        )

        result = await evaluator.evaluate(record, llm)

        assert result.score == 8
        llm.generate_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_failure_raises(self):
        evaluator = QualityEvaluator()
        llm = MagicMock()
        llm.generate_json = AsyncMock(side_effect=RuntimeError("API error"))
        record = _make_staged()

        with pytest.raises(RuntimeError, match="API error"):
            await evaluator.evaluate(record, llm)

    @pytest.mark.asyncio
    async def test_non_dict_response(self):
        """LLM returns non-dict → should result in reject with score 0."""
        evaluator = QualityEvaluator()
        llm = MagicMock()
        llm.generate_json = AsyncMock(return_value=(
            "not a dict",
            {"input_tokens": 10, "output_tokens": 5},
        ))
        record = _make_staged()

        result = await evaluator.evaluate(record, llm)

        assert result.score == 0
        assert result.verdict == "reject"

    @pytest.mark.asyncio
    async def test_issues_captured(self):
        evaluator = QualityEvaluator(min_score=7)
        llm = _make_mock_llm(
            score=5, verdict="reject",
            issues=["Missing key findings", "Generic answer"],
        )
        record = _make_staged()

        result = await evaluator.evaluate(record, llm)

        assert len(result.issues) == 2
        assert "Missing key findings" in result.issues

    @pytest.mark.asyncio
    async def test_custom_min_score(self):
        evaluator = QualityEvaluator(min_score=9)
        llm = _make_mock_llm(score=8, verdict="promote")
        record = _make_staged()

        result = await evaluator.evaluate(record, llm)

        # Score 8 < min_score 9 → reject
        assert result.verdict == "reject"

    @pytest.mark.asyncio
    async def test_no_steps_format(self):
        """Record with no steps should format properly."""
        evaluator = QualityEvaluator(min_score=7)
        llm = _make_mock_llm(score=8)
        record = _make_staged(mode="simple", steps=[])

        result = await evaluator.evaluate(record, llm)

        assert result.score == 8
        # Check the prompt included the no-steps message
        call_args = llm.generate_json.call_args
        prompt = call_args[0][0][0].content
        assert "no execution steps" in prompt


class TestClamp:
    def test_normal_range(self):
        assert _clamp(5) == 5

    def test_below_low(self):
        assert _clamp(-3) == 0

    def test_above_high(self):
        assert _clamp(15) == 10

    def test_float_converted(self):
        assert _clamp(7.8) == 7

    def test_invalid_type(self):
        assert _clamp("invalid") == 0

    def test_none(self):
        assert _clamp(None) == 0
