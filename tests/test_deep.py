"""Tests for v3.0.x — Deep Analysis.

Covers blueprint creation, investigation orchestration, reasoning loop,
deep synthesis, streaming events, and metamode submode classification.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.state import AgentState, BASE_MODES
from mcpdb.agent.subgraphs.deep import (
    run_deep,
    _create_blueprint,
    _run_investigation,
    _reason_about_results,
    _deep_synthesize,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm():
    """Create a mock LLM with configurable responses."""
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
        "question": "Investigate customer churn patterns",
        "source_context": "Test DB with customers, orders tables",
        "active_source_ids": ["test_db"],
        "query_mode": "deep",
        "target_sources": ["test_db"],
        "requires_cross_source": False,
        "key_entities": ["customers", "orders"],
        "response": None,
        "validation_result": None,
        "replan_count": 0,
        "artifacts": [],
        "execution_log": [],
        "max_retries": 2,
    }


# ---------------------------------------------------------------------------
# Blueprint creation tests
# ---------------------------------------------------------------------------

class TestCreateBlueprint:
    @pytest.mark.asyncio
    async def test_create_blueprint(self, mock_llm, callbacks, base_state):
        mock_llm.generate_json.return_value = (
            {
                "research_goal": "Understand customer churn patterns",
                "investigations": [
                    {"id": 1, "question": "What is the churn rate?", "approach": "SQL count", "priority": "high"},
                    {"id": 2, "question": "Which segments churn most?", "approach": "Group analysis", "priority": "high"},
                    {"id": 3, "question": "What predicts churn?", "approach": "Correlation", "priority": "medium"},
                ],
            },
            {"input_tokens": 100, "output_tokens": 200},
        )

        blueprint = await _create_blueprint(base_state, mock_llm, callbacks)
        assert blueprint is not None
        assert blueprint["research_goal"] == "Understand customer churn patterns"
        assert len(blueprint["investigations"]) == 3

    @pytest.mark.asyncio
    async def test_blueprint_failure(self, mock_llm, callbacks, base_state):
        mock_llm.generate_json.side_effect = Exception("LLM error")

        blueprint = await _create_blueprint(base_state, mock_llm, callbacks)
        assert blueprint is None


# ---------------------------------------------------------------------------
# Investigation tests
# ---------------------------------------------------------------------------

class TestRunInvestigation:
    @pytest.mark.asyncio
    async def test_investigation_success(self, mock_llm, callbacks, mock_registry, base_state):
        # Mock the simple mode pipeline
        mock_llm.generate_json.return_value = (
            {
                "analysis": "Churn rate analysis",
                "approach": "SQL query",
                "steps": [{"step_number": 1, "action": "sql", "code": "SELECT COUNT(*) FROM customers"}],
            },
            {"input_tokens": 50, "output_tokens": 100},
        )
        mock_llm.generate.return_value = (
            "The churn rate is 15%.",
            {"input_tokens": 50, "output_tokens": 30},
        )

        result = await _run_investigation(
            "What is the churn rate?",
            base_state, mock_llm, callbacks, mock_registry,
        )
        assert isinstance(result, dict)
        assert "response" in result
        assert len(result["response"]) > 0
        assert "artifacts" in result


# ---------------------------------------------------------------------------
# Reasoning loop tests
# ---------------------------------------------------------------------------

class TestReasoningLoop:
    @pytest.mark.asyncio
    async def test_reasoning_continue(self, mock_llm, callbacks):
        mock_llm.generate_json.return_value = (
            {
                "sufficient": False,
                "skip_ids": [],
                "new_investigations": [],
                "reasoning": "Need more data on temporal patterns.",
            },
            {"input_tokens": 100, "output_tokens": 50},
        )

        result = await _reason_about_results(
            goal="Understand churn",
            completed=[
                {"id": 1, "question": "Churn rate?", "approach": "", "result": "15%"},
            ],
            remaining=[
                {"id": 2, "question": "Churn by segment?"},
            ],
            llm=mock_llm,
            callbacks=callbacks,
        )

        assert result is not None
        assert result["sufficient"] is False

    @pytest.mark.asyncio
    async def test_reasoning_sufficient(self, mock_llm, callbacks):
        mock_llm.generate_json.return_value = (
            {
                "sufficient": True,
                "skip_ids": [3],
                "new_investigations": [],
                "reasoning": "We have enough evidence.",
            },
            {"input_tokens": 100, "output_tokens": 50},
        )

        result = await _reason_about_results(
            goal="Understand churn",
            completed=[
                {"id": 1, "question": "Churn rate?", "approach": "", "result": "15%"},
                {"id": 2, "question": "Segments?", "approach": "", "result": "Enterprise: 5%, SMB: 25%"},
            ],
            remaining=[
                {"id": 3, "question": "Temporal patterns?"},
            ],
            llm=mock_llm,
            callbacks=callbacks,
        )

        assert result is not None
        assert result["sufficient"] is True
        assert 3 in result["skip_ids"]

    @pytest.mark.asyncio
    async def test_reasoning_adds_investigations(self, mock_llm, callbacks):
        mock_llm.generate_json.return_value = (
            {
                "sufficient": False,
                "skip_ids": [],
                "new_investigations": [
                    {"id": 10, "question": "What is the impact on revenue?", "approach": "Revenue analysis"},
                ],
                "reasoning": "Found interesting revenue correlation.",
            },
            {"input_tokens": 100, "output_tokens": 50},
        )

        result = await _reason_about_results(
            goal="Understand churn", completed=[], remaining=[],
            llm=mock_llm, callbacks=callbacks,
        )

        assert len(result["new_investigations"]) == 1

    @pytest.mark.asyncio
    async def test_reasoning_failure(self, mock_llm, callbacks):
        mock_llm.generate_json.side_effect = Exception("LLM error")

        result = await _reason_about_results(
            goal="Test", completed=[], remaining=[],
            llm=mock_llm, callbacks=callbacks,
        )
        assert result is None


# ---------------------------------------------------------------------------
# Deep synthesis tests
# ---------------------------------------------------------------------------

class TestDeepSynthesize:
    @pytest.mark.asyncio
    async def test_synthesis(self, mock_llm, callbacks, base_state):
        mock_llm.generate.return_value = (
            "# Research Report\n\n## Executive Summary\nChurn is at 15%...",
            {"input_tokens": 500, "output_tokens": 300},
        )

        state = await _deep_synthesize(
            base_state,
            goal="Understand churn",
            completed=[
                {"id": 1, "question": "Churn rate?", "result": "15%"},
                {"id": 2, "question": "Segments?", "result": "Enterprise: 5%"},
            ],
            reasoning_log=["Found patterns in segment data"],
            llm=mock_llm,
            callbacks=callbacks,
        )

        assert state.get("response") is not None
        assert "Research Report" in state["response"]

    @pytest.mark.asyncio
    async def test_synthesis_fallback(self, mock_llm, callbacks, base_state):
        mock_llm.generate.side_effect = Exception("LLM error")

        state = await _deep_synthesize(
            base_state,
            goal="Understand churn",
            completed=[
                {"id": 1, "question": "Churn rate?", "result": "15%"},
            ],
            reasoning_log=[],
            llm=mock_llm,
            callbacks=callbacks,
        )

        assert state.get("response") is not None
        assert "Research Report" in state["response"]
        assert "15%" in state["response"]


# ---------------------------------------------------------------------------
# Full deep analysis flow tests
# ---------------------------------------------------------------------------

class TestRunDeep:
    @pytest.mark.asyncio
    async def test_full_deep_flow(self, mock_llm, callbacks, mock_registry, base_state):
        """Full deep flow with classify_question + dispatch_base_mode."""
        # Blueprint via generate_json
        mock_llm.generate_json.side_effect = [
            # Blueprint creation
            (
                {
                    "research_goal": "Understand churn",
                    "investigations": [
                        {"id": 1, "question": "Churn rate?", "approach": "SQL", "priority": "high"},
                        {"id": 2, "question": "Segments?", "approach": "Group by", "priority": "high"},
                    ],
                },
                {"input_tokens": 100, "output_tokens": 200},
            ),
            # Reasoning (after investigation 2 completes)
            (
                {"sufficient": True, "skip_ids": [], "new_investigations": [], "reasoning": "Done"},
                {"input_tokens": 100, "output_tokens": 50},
            ),
        ]

        # Synthesis response
        mock_llm.generate.return_value = (
            "# Report\n\nChurn analysis complete.",
            {"input_tokens": 200, "output_tokens": 300},
        )

        async def mock_classify(question, source_context, llm, allowed_modes=None):
            return {"mode": "simple", "reasoning": "data query", "target_sources": [],
                    "requires_cross_source": False, "key_entities": []}

        async def mock_dispatch(state, llm, cb, registry):
            state["response"] = f"Result for: {state['question']}"
            return state

        with patch("mcpdb.agent.subgraphs.deep.classify_question", side_effect=mock_classify), \
             patch("mcpdb.agent.subgraphs.deep.dispatch_base_mode", side_effect=mock_dispatch):
            state = await run_deep(base_state, mock_llm, callbacks, mock_registry)

        assert state.get("response") is not None

        # Check events
        events = callbacks.get_events()
        event_types = [e.type for e in events]
        assert "deep/start" in event_types
        assert "deep/blueprint" in event_types
        assert "deep/complete" in event_types

    @pytest.mark.asyncio
    async def test_deep_blueprint_failure(self, mock_llm, callbacks, mock_registry, base_state):
        mock_llm.generate_json.side_effect = Exception("LLM error")

        state = await run_deep(base_state, mock_llm, callbacks, mock_registry)
        assert "Could not create" in state.get("response", "")

    @pytest.mark.asyncio
    async def test_deep_max_iterations(self, mock_llm, callbacks, mock_registry, base_state):
        """Deep analysis respects max_iterations."""
        mock_llm.generate_json.side_effect = [
            # Blueprint
            (
                {
                    "research_goal": "Big research",
                    "investigations": [
                        {"id": i, "question": f"Q{i}?", "approach": "SQL", "priority": "medium"}
                        for i in range(20)
                    ],
                },
                {"input_tokens": 100, "output_tokens": 200},
            ),
            # Reasoning (never sufficient)
            ({"sufficient": False, "skip_ids": [], "new_investigations": [], "reasoning": "More"}, {"input_tokens": 50, "output_tokens": 50}),
            ({"sufficient": False, "skip_ids": [], "new_investigations": [], "reasoning": "More"}, {"input_tokens": 50, "output_tokens": 50}),
        ]

        mock_llm.generate.return_value = (
            "Fallback report", {"input_tokens": 50, "output_tokens": 30},
        )

        async def mock_classify(question, source_context, llm, allowed_modes=None):
            return {"mode": "simple", "reasoning": "ok", "target_sources": [],
                    "requires_cross_source": False, "key_entities": []}

        async def mock_dispatch(state, llm, cb, registry):
            state["response"] = "Result"
            return state

        with patch("mcpdb.agent.subgraphs.deep.classify_question", side_effect=mock_classify), \
             patch("mcpdb.agent.subgraphs.deep.dispatch_base_mode", side_effect=mock_dispatch):
            state = await run_deep(
                base_state, mock_llm, callbacks, mock_registry,
                max_iterations=3,
            )

        # Should have completed at most 3 investigations
        events = callbacks.get_events()
        inv_starts = [e for e in events if e.type == "deep/investigation_start"]
        assert len(inv_starts) <= 3


# ---------------------------------------------------------------------------
# Agent graph integration tests
# ---------------------------------------------------------------------------

class TestDeepInGraph:
    @pytest.mark.asyncio
    async def test_deep_mode_override(self, mock_llm, mock_registry, callbacks):
        from mcpdb.agent.graph import run_agent

        mock_llm.generate_json.side_effect = [
            # Blueprint
            (
                {
                    "research_goal": "Test",
                    "investigations": [
                        {"id": 1, "question": "Q1?", "approach": "SQL", "priority": "high"},
                    ],
                },
                {"input_tokens": 50, "output_tokens": 100},
            ),
            # Reasoning
            ({"sufficient": True, "skip_ids": [], "new_investigations": [], "reasoning": "Done"}, {"input_tokens": 50, "output_tokens": 50}),
        ]
        mock_llm.generate.side_effect = [
            ("Final report", {"input_tokens": 200, "output_tokens": 200}),
        ]

        async def mock_classify(question, source_context, llm, allowed_modes=None):
            return {"mode": "simple", "reasoning": "ok", "target_sources": [],
                    "requires_cross_source": False, "key_entities": []}

        async def mock_dispatch(state, llm, cb, registry):
            state["response"] = "Investigation result"
            return state

        with patch("mcpdb.agent.subgraphs.deep.classify_question", side_effect=mock_classify), \
             patch("mcpdb.agent.subgraphs.deep.dispatch_base_mode", side_effect=mock_dispatch):
            state = await run_agent(
                question="Investigate churn",
                registry=mock_registry,
                llm=mock_llm,
                callbacks=callbacks,
                mode_override="deep",
            )

        assert state.get("query_mode") == "deep"
        assert state.get("response") is not None

    @pytest.mark.asyncio
    async def test_deep_mode_in_classify(self, mock_llm, mock_registry, callbacks):
        """Classify can route to deep mode."""
        from mcpdb.agent.nodes.classify import classify

        mock_llm.generate_json.return_value = (
            {
                "mode": "deep",
                "reasoning": "Requires multi-investigation research",
                "target_sources": ["test_db"],
                "requires_cross_source": False,
                "key_entities": ["customers"],
            },
            {"input_tokens": 50, "output_tokens": 30},
        )

        state: AgentState = {
            "question": "Do a comprehensive audit of data quality",
            "source_context": "Test schema",
            "active_source_ids": ["test_db"],
        }

        state = await classify(state, mock_llm, callbacks)
        assert state["query_mode"] == "deep"


# ---------------------------------------------------------------------------
# Deep metamode submode classification tests
# ---------------------------------------------------------------------------


class TestDeepSubmode:
    """Test that deep mode classifies each investigation independently."""

    @pytest.mark.asyncio
    async def test_each_investigation_classified(self, mock_llm, callbacks, mock_registry, base_state):
        """Each investigation gets its own classify_question call."""
        mock_llm.generate_json.side_effect = [
            # Blueprint
            (
                {
                    "research_goal": "Research",
                    "investigations": [
                        {"id": 1, "question": "Schema overview?", "approach": "Schema", "priority": "high"},
                        {"id": 2, "question": "Revenue trends?", "approach": "SQL", "priority": "high"},
                        {"id": 3, "question": "Churn deep dive?", "approach": "Complex", "priority": "medium"},
                    ],
                },
                {"input_tokens": 100, "output_tokens": 200},
            ),
            # Reasoning after inv 2
            ({"sufficient": False, "skip_ids": [], "new_investigations": [], "reasoning": "Continue"}, {"input_tokens": 50, "output_tokens": 50}),
            # Reasoning after inv 3
            ({"sufficient": True, "skip_ids": [], "new_investigations": [], "reasoning": "Done"}, {"input_tokens": 50, "output_tokens": 50}),
        ]
        mock_llm.generate.return_value = ("Report", {"input_tokens": 50, "output_tokens": 50})

        classify_modes = ["quick", "simple", "extended"]
        classify_idx = [0]

        async def mock_classify(question, source_context, llm, allowed_modes=None):
            mode = classify_modes[classify_idx[0]]
            classify_idx[0] += 1
            return {"mode": mode, "reasoning": "ok", "target_sources": [],
                    "requires_cross_source": False, "key_entities": []}

        async def mock_dispatch(state, llm, cb, registry):
            state["response"] = f"Result ({state['query_mode']})"
            return state

        with patch("mcpdb.agent.subgraphs.deep.classify_question", side_effect=mock_classify), \
             patch("mcpdb.agent.subgraphs.deep.dispatch_base_mode", side_effect=mock_dispatch):
            state = await run_deep(base_state, mock_llm, callbacks, mock_registry)

        assert classify_idx[0] == 3  # 3 investigations → 3 classify calls

    @pytest.mark.asyncio
    async def test_submode_in_deep_callbacks(self, mock_llm, callbacks, mock_registry, base_state):
        """Callbacks include submode in investigation_start and investigation_complete."""
        mock_llm.generate_json.side_effect = [
            (
                {
                    "research_goal": "Research",
                    "investigations": [
                        {"id": 1, "question": "Q1?", "approach": "SQL", "priority": "high"},
                        {"id": 2, "question": "Q2?", "approach": "Analysis", "priority": "high"},
                    ],
                },
                {"input_tokens": 100, "output_tokens": 200},
            ),
            ({"sufficient": True, "skip_ids": [], "new_investigations": [], "reasoning": "Done"}, {"input_tokens": 50, "output_tokens": 50}),
        ]
        mock_llm.generate.return_value = ("Report", {"input_tokens": 50, "output_tokens": 50})

        submodes = ["quick", "extended"]
        idx = [0]

        async def mock_classify(question, source_context, llm, allowed_modes=None):
            mode = submodes[idx[0]]
            idx[0] += 1
            return {"mode": mode, "reasoning": "ok", "target_sources": [],
                    "requires_cross_source": False, "key_entities": []}

        async def mock_dispatch(state, llm, cb, registry):
            state["response"] = "Result"
            return state

        with patch("mcpdb.agent.subgraphs.deep.classify_question", side_effect=mock_classify), \
             patch("mcpdb.agent.subgraphs.deep.dispatch_base_mode", side_effect=mock_dispatch):
            await run_deep(base_state, mock_llm, callbacks, mock_registry)

        events = callbacks.get_events()
        inv_starts = [e for e in events if e.type == "deep/investigation_start"]
        inv_completes = [e for e in events if e.type == "deep/investigation_complete"]

        assert len(inv_starts) == 2
        assert inv_starts[0].data["submode"] == "quick"
        assert inv_starts[1].data["submode"] == "extended"
        assert inv_completes[0].data["submode"] == "quick"
        assert inv_completes[1].data["submode"] == "extended"

    @pytest.mark.asyncio
    async def test_classify_restricted_to_base_modes(self, mock_llm, callbacks, mock_registry, base_state):
        """classify_question in deep mode is called with allowed_modes=BASE_MODES."""
        mock_llm.generate_json.side_effect = [
            (
                {
                    "research_goal": "Research",
                    "investigations": [
                        {"id": 1, "question": "Q?", "approach": "SQL", "priority": "high"},
                    ],
                },
                {"input_tokens": 100, "output_tokens": 200},
            ),
            ({"sufficient": True, "skip_ids": [], "new_investigations": [], "reasoning": "Done"}, {"input_tokens": 50, "output_tokens": 50}),
        ]
        mock_llm.generate.return_value = ("Report", {"input_tokens": 50, "output_tokens": 50})

        captured_allowed = []

        async def mock_classify(question, source_context, llm, allowed_modes=None):
            captured_allowed.append(allowed_modes)
            return {"mode": "simple", "reasoning": "ok", "target_sources": [],
                    "requires_cross_source": False, "key_entities": []}

        async def mock_dispatch(state, llm, cb, registry):
            state["response"] = "Result"
            return state

        with patch("mcpdb.agent.subgraphs.deep.classify_question", side_effect=mock_classify), \
             patch("mcpdb.agent.subgraphs.deep.dispatch_base_mode", side_effect=mock_dispatch):
            await run_deep(base_state, mock_llm, callbacks, mock_registry)

        assert all(am == BASE_MODES for am in captured_allowed)

    @pytest.mark.asyncio
    async def test_visualization_hint_passed_to_classifier(self, mock_llm, callbacks, mock_registry, base_state):
        """needs_visualization flag appends hint before classification."""
        mock_llm.generate_json.side_effect = [
            (
                {
                    "research_goal": "Research",
                    "investigations": [
                        {"id": 1, "question": "Distribution?", "approach": "Chart", "priority": "high", "needs_visualization": True},
                    ],
                },
                {"input_tokens": 100, "output_tokens": 200},
            ),
            ({"sufficient": True, "skip_ids": [], "new_investigations": [], "reasoning": "Done"}, {"input_tokens": 50, "output_tokens": 50}),
        ]
        mock_llm.generate.return_value = ("Report", {"input_tokens": 50, "output_tokens": 50})

        classified_questions = []

        async def mock_classify(question, source_context, llm, allowed_modes=None):
            classified_questions.append(question)
            return {"mode": "simple", "reasoning": "ok", "target_sources": [],
                    "requires_cross_source": False, "key_entities": []}

        async def mock_dispatch(state, llm, cb, registry):
            state["response"] = "Chart result"
            return state

        with patch("mcpdb.agent.subgraphs.deep.classify_question", side_effect=mock_classify), \
             patch("mcpdb.agent.subgraphs.deep.dispatch_base_mode", side_effect=mock_dispatch):
            await run_deep(base_state, mock_llm, callbacks, mock_registry)

        assert len(classified_questions) == 1
        assert "visualization" in classified_questions[0].lower()
        assert "Distribution?" in classified_questions[0]
