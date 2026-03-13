"""Tests for Sequential mode."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.state import AgentState
from mcpdb.agent.subgraphs.sequential import (
    parse_questions,
    _build_prior_context,
    run_sequential,
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
        lines = [f"Question {i}" for i in range(150)]
        result = parse_questions("\n".join(lines))
        assert len(result) == 100  # MAX_QUESTIONS

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


# ---------------------------------------------------------------------------
# Fixtures for async tests
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.generate = AsyncMock()
    llm.generate_json = AsyncMock()
    return llm


@pytest.fixture
def mock_registry():
    registry = MagicMock()
    registry.list_sources.return_value = []
    registry.get_combined_context.return_value = "Test schema"
    registry.get_queryable_sources.return_value = []
    return registry


@pytest.fixture
def callbacks():
    return CallbackManager()


@pytest.fixture
def base_state():
    return {
        "question": "Q1\nQ2\nQ3",
        "source_context": "Test DB with users, orders tables",
        "active_source_ids": ["test_db"],
        "query_mode": "sequential",
        "target_sources": ["test_db"],
        "requires_cross_source": False,
        "key_entities": [],
        "response": None,
        "validation_result": None,
        "replan_count": 0,
        "artifacts": [],
        "execution_log": [],
        "max_retries": 2,
    }


# ---------------------------------------------------------------------------
# Metamode submode classification tests
# ---------------------------------------------------------------------------


class TestSequentialSubmode:
    """Test that sequential mode classifies each sub-question independently."""

    @pytest.mark.asyncio
    async def test_each_step_classified_independently(self, mock_llm, callbacks, mock_registry, base_state):
        """Each question in sequence gets its own classify_question call."""
        base_state["question"] = "What tables exist?\nShow top 10 customers"

        # classify_question returns different submodes per question
        classify_results = [
            {"mode": "quick", "reasoning": "schema", "target_sources": [], "requires_cross_source": False, "key_entities": []},
            {"mode": "simple", "reasoning": "data query", "target_sources": [], "requires_cross_source": False, "key_entities": ["customers"]},
        ]
        classify_call_count = [0]

        async def mock_classify(question, source_context, llm, allowed_modes=None):
            idx = classify_call_count[0]
            classify_call_count[0] += 1
            return classify_results[idx]

        # dispatch_base_mode returns a canned response
        async def mock_dispatch(state, llm, cb, registry):
            state["response"] = f"Result for mode {state['query_mode']}"
            return state

        mock_llm.generate.return_value = ("Synthesis", {"input_tokens": 50, "output_tokens": 50})

        with patch("mcpdb.agent.subgraphs.sequential.classify_question", side_effect=mock_classify) as mock_cls, \
             patch("mcpdb.agent.subgraphs.sequential.dispatch_base_mode", side_effect=mock_dispatch):
            state = await run_sequential(base_state, mock_llm, callbacks, mock_registry)

        # Two questions → two classify calls
        assert classify_call_count[0] == 2

    @pytest.mark.asyncio
    async def test_submode_in_callbacks(self, mock_llm, callbacks, mock_registry, base_state):
        """Callbacks include submode field in step_start and step_complete events."""
        base_state["question"] = "What tables exist?\nAnalyze revenue"

        classify_results = [
            {"mode": "quick", "reasoning": "schema", "target_sources": [], "requires_cross_source": False, "key_entities": []},
            {"mode": "extended", "reasoning": "complex", "target_sources": [], "requires_cross_source": False, "key_entities": []},
        ]
        call_idx = [0]

        async def mock_classify(question, source_context, llm, allowed_modes=None):
            idx = call_idx[0]
            call_idx[0] += 1
            return classify_results[idx]

        async def mock_dispatch(state, llm, cb, registry):
            state["response"] = "Result"
            return state

        mock_llm.generate.return_value = ("Synthesis", {"input_tokens": 50, "output_tokens": 50})

        with patch("mcpdb.agent.subgraphs.sequential.classify_question", side_effect=mock_classify), \
             patch("mcpdb.agent.subgraphs.sequential.dispatch_base_mode", side_effect=mock_dispatch):
            await run_sequential(base_state, mock_llm, callbacks, mock_registry)

        events = callbacks.get_events()
        step_starts = [e for e in events if e.type == "sequential/step_start"]
        step_completes = [e for e in events if e.type == "sequential/step_complete"]

        assert len(step_starts) == 2
        assert step_starts[0].data["submode"] == "quick"
        assert step_starts[1].data["submode"] == "extended"
        assert step_completes[0].data["submode"] == "quick"
        assert step_completes[1].data["submode"] == "extended"

    @pytest.mark.asyncio
    async def test_classify_uses_base_modes_only(self, mock_llm, callbacks, mock_registry, base_state):
        """classify_question is called with allowed_modes=BASE_MODES (no metamodes)."""
        base_state["question"] = "Question A\nQuestion B"

        from mcpdb.agent.state import BASE_MODES
        captured_allowed = []

        async def mock_classify(question, source_context, llm, allowed_modes=None):
            captured_allowed.append(allowed_modes)
            return {"mode": "simple", "reasoning": "ok", "target_sources": [], "requires_cross_source": False, "key_entities": []}

        async def mock_dispatch(state, llm, cb, registry):
            state["response"] = "Result"
            return state

        mock_llm.generate.return_value = ("Synthesis", {"input_tokens": 50, "output_tokens": 50})

        with patch("mcpdb.agent.subgraphs.sequential.classify_question", side_effect=mock_classify), \
             patch("mcpdb.agent.subgraphs.sequential.dispatch_base_mode", side_effect=mock_dispatch):
            await run_sequential(base_state, mock_llm, callbacks, mock_registry)

        # Both calls should restrict to BASE_MODES
        assert all(am == BASE_MODES for am in captured_allowed)

    @pytest.mark.asyncio
    async def test_single_question_classifies_and_dispatches(self, mock_llm, callbacks, mock_registry, base_state):
        """Single-question degenerate case still classifies and dispatches."""
        base_state["question"] = "Show top 10 customers"

        async def mock_classify(question, source_context, llm, allowed_modes=None):
            return {"mode": "extended", "reasoning": "complex", "target_sources": [], "requires_cross_source": False, "key_entities": []}

        async def mock_dispatch(state, llm, cb, registry):
            state["response"] = "Extended result"
            return state

        with patch("mcpdb.agent.subgraphs.sequential.classify_question", side_effect=mock_classify) as mock_cls, \
             patch("mcpdb.agent.subgraphs.sequential.dispatch_base_mode", side_effect=mock_dispatch) as mock_disp:
            state = await run_sequential(base_state, mock_llm, callbacks, mock_registry)

        assert state["query_mode"] == "extended"
        assert state["response"] == "Extended result"
        mock_disp.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sequential_results_include_submode(self, mock_llm, callbacks, mock_registry, base_state):
        """sequential_results stored in state include submode for each step."""
        base_state["question"] = "Q1\nQ2"

        submodes = ["quick", "optimization_required"]
        idx = [0]

        async def mock_classify(question, source_context, llm, allowed_modes=None):
            mode = submodes[idx[0]]
            idx[0] += 1
            return {"mode": mode, "reasoning": "ok", "target_sources": [], "requires_cross_source": False, "key_entities": []}

        async def mock_dispatch(state, llm, cb, registry):
            state["response"] = "Result"
            return state

        mock_llm.generate.return_value = ("Synthesis", {"input_tokens": 50, "output_tokens": 50})

        with patch("mcpdb.agent.subgraphs.sequential.classify_question", side_effect=mock_classify), \
             patch("mcpdb.agent.subgraphs.sequential.dispatch_base_mode", side_effect=mock_dispatch):
            state = await run_sequential(base_state, mock_llm, callbacks, mock_registry)

        results = state["sequential_results"]
        assert results[0]["submode"] == "quick"
        assert results[1]["submode"] == "optimization_required"
