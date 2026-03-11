"""Tests for Sequential mode."""

from __future__ import annotations

import pytest

from mcpdb.agent.subgraphs.sequential import (
    parse_questions,
    _build_prior_context,
)


class TestParseQuestions:
    """Test question parsing from multi-line input."""

    def test_newline_separated(self):
        text = "What is total revenue?\nWhich region leads?\nHow does it trend?"
        result = parse_questions(text)
        assert result == [
            "What is total revenue?",
            "Which region leads?",
            "How does it trend?",
        ]

    def test_numbered_list(self):
        text = "1. What is total revenue?\n2. Which region leads?\n3. How does it trend?"
        result = parse_questions(text)
        assert result == [
            "What is total revenue?",
            "Which region leads?",
            "How does it trend?",
        ]

    def test_numbered_with_parenthesis(self):
        text = "1) First question\n2) Second question"
        result = parse_questions(text)
        assert result == ["First question", "Second question"]

    def test_bullet_points(self):
        text = "- What is revenue?\n- What is profit?\n* What is margin?"
        result = parse_questions(text)
        assert result == [
            "What is revenue?",
            "What is profit?",
            "What is margin?",
        ]

    def test_blank_lines_filtered(self):
        text = "First question\n\nSecond question\n\n\nThird question"
        result = parse_questions(text)
        assert result == ["First question", "Second question", "Third question"]

    def test_single_question(self):
        text = "What is total revenue?"
        result = parse_questions(text)
        assert result == ["What is total revenue?"]

    def test_max_questions_limit(self):
        lines = [f"Question {i}" for i in range(30)]
        result = parse_questions("\n".join(lines))
        assert len(result) == 20  # MAX_QUESTIONS

    def test_whitespace_stripped(self):
        text = "  What is revenue?  \n  What is profit?  "
        result = parse_questions(text)
        assert result == ["What is revenue?", "What is profit?"]

    def test_empty_input(self):
        assert parse_questions("") == []
        assert parse_questions("   ") == []

    def test_mixed_format(self):
        text = "1. First\n- Second\n3) Third\nFourth"
        result = parse_questions(text)
        assert result == ["First", "Second", "Third", "Fourth"]


class TestBuildPriorContext:
    """Test context accumulation."""

    def test_empty_results(self):
        assert _build_prior_context([]) == ""

    def test_single_result(self):
        results = [{"index": 0, "question": "Q1", "response": "Answer 1"}]
        ctx = _build_prior_context(results)
        assert "Q1" in ctx
        assert "Answer 1" in ctx
        assert "PREVIOUS Q&A CONTEXT" in ctx

    def test_multiple_results(self):
        results = [
            {"index": 0, "question": "Q1", "response": "A1"},
            {"index": 1, "question": "Q2", "response": "A2"},
        ]
        ctx = _build_prior_context(results)
        assert "Q1" in ctx
        assert "Q2" in ctx
        assert "A1" in ctx
        assert "A2" in ctx

    def test_long_answers_truncated(self):
        long_answer = "x" * 2000
        results = [{"index": 0, "question": "Q1", "response": long_answer}]
        ctx = _build_prior_context(results)
        assert len(ctx) < len(long_answer)
        assert "..." in ctx


class TestSequentialStateType:
    """Test that sequential mode is properly registered."""

    def test_mode_in_state_literal(self):
        from mcpdb.agent.state import AgentState
        state: AgentState = {"query_mode": "sequential"}
        assert state["query_mode"] == "sequential"

    def test_mode_in_cache_rank(self):
        from mcpdb.experience.cache import ExperienceCache
        assert "sequential" in ExperienceCache._MODE_RANK

    def test_mode_in_common_descriptions(self):
        from mcpdb.agent.nodes.common import MODE_DESCRIPTIONS
        assert "sequential" in MODE_DESCRIPTIONS

    def test_mode_in_progress_colors(self):
        from mcpdb.cli.progress import MODE_COLORS
        assert "sequential" in MODE_COLORS
