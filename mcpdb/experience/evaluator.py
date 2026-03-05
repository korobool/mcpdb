"""Quality evaluator — LLM-based scoring for staged results.

Evaluates data analysis responses on 4 dimensions:
- completeness: Does it fully answer the question?
- accuracy: Are the numbers/facts correct given execution results?
- relevance: Does it address what was asked, without irrelevant info?
- clarity: Is it well-structured and easy to understand?

Returns a QualityResult with an overall score (1-10) and verdict
("promote" or "reject"). The verdict is determined by comparing the
score against a configurable threshold (default: 7).

Quick-mode responses with no executable steps are auto-promoted
(score 10) since they're schema-derived and deterministic — no LLM
evaluation needed.
"""

from __future__ import annotations

import logging
from typing import Any

from mcpdb.experience.records import QualityResult, StagedRecord

logger = logging.getLogger("mcpdb.experience.evaluator")

_EVALUATION_PROMPT = """\
You are evaluating the quality of a data analysis response.

QUESTION: {question}
MODE: {query_mode}

EXECUTION STEPS:
{steps_summary}

RESPONSE:
{response}

Score this response on 4 dimensions (1-10 each):
- completeness: Does it fully answer the question?
- accuracy: Are the numbers/facts correct given the execution results?
- relevance: Does it address what was asked, without irrelevant info?
- clarity: Is it well-structured and easy to understand?

Also check for red flags:
- Hallucinated numbers not from execution results
- Missing key findings from the data
- Contradictions between response and execution results
- Generic/vague answers that don't use the actual data

Respond with JSON:
{{"score": <1-10 overall>, "completeness": <1-10>, "accuracy": <1-10>,\
 "relevance": <1-10>, "clarity": <1-10>,\
 "issues": ["issue1", ...], "verdict": "promote"|"reject"}}
"""


class QualityEvaluator:
    """Evaluates staged records using LLM-based quality scoring.

    Quick-mode responses are auto-promoted (score 10) since they're
    schema-derived and deterministic.
    """

    def __init__(self, min_score: int = 7) -> None:
        self._min_score = min_score

    async def evaluate(
        self,
        record: StagedRecord,
        llm: Any,
    ) -> QualityResult:
        """Evaluate a staged record's quality.

        Returns a QualityResult with score and verdict.
        Quick-mode responses with no executable steps are auto-promoted.
        """
        # Fast-path: quick mode with no executable steps → auto-promote
        executable = [s for s in record.steps if s.action_type in ("sql", "python", "schema", "sample")]
        if record.query_mode == "quick" and not executable:
            logger.debug("Auto-promoting quick-mode result: %s", record.intent_hash)
            return QualityResult(
                score=10,
                completeness=10,
                accuracy=10,
                relevance=10,
                clarity=10,
                issues=[],
                verdict="promote",
            )

        # Build steps summary for the prompt
        steps_summary = self._format_steps(record)

        prompt = _EVALUATION_PROMPT.format(
            question=record.question,
            query_mode=record.query_mode,
            steps_summary=steps_summary,
            response=record.response,
        )

        from mcpdb.llm.provider import Message

        try:
            result, _usage = await llm.generate_json(
                [Message(role="user", content=prompt)],
                temperature=0.1,
            )
        except Exception as e:
            logger.warning("LLM evaluation failed: %s", e)
            raise

        return self._parse_result(result)

    def _format_steps(self, record: StagedRecord) -> str:
        """Format execution steps for the evaluation prompt."""
        if not record.steps:
            return "(no execution steps — schema-only response)"

        lines = []
        for i, step in enumerate(record.steps, 1):
            lines.append(f"Step {i} [{step.action_type}]:")
            lines.append(f"  Code: {step.code[:500]}")
            if step.result_preview:
                lines.append(f"  Result: {step.result_preview[:300]}")
        return "\n".join(lines)

    def _parse_result(self, result: Any) -> QualityResult:
        """Parse LLM response into a QualityResult."""
        if not isinstance(result, dict):
            logger.warning("Unexpected evaluation response type: %s", type(result))
            return QualityResult(
                score=0, completeness=0, accuracy=0,
                relevance=0, clarity=0,
                issues=["LLM returned non-dict response"],
                verdict="reject",
            )

        score = _clamp(result.get("score", 0))
        completeness = _clamp(result.get("completeness", 0))
        accuracy = _clamp(result.get("accuracy", 0))
        relevance = _clamp(result.get("relevance", 0))
        clarity = _clamp(result.get("clarity", 0))
        issues = result.get("issues", [])
        if not isinstance(issues, list):
            issues = [str(issues)]

        # Determine verdict based on score threshold
        verdict = "promote" if score >= self._min_score else "reject"

        return QualityResult(
            score=score,
            completeness=completeness,
            accuracy=accuracy,
            relevance=relevance,
            clarity=clarity,
            issues=issues,
            verdict=verdict,
        )


def _clamp(value: Any, low: int = 0, high: int = 10) -> int:
    """Clamp a value to [low, high] range, converting to int."""
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return 0
