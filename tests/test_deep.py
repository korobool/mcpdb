"""Tests for v3.0.x — Deep Analysis.

Covers blueprint creation, investigation orchestration, reasoning loop,
deep synthesis, and streaming events.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcpdb.agent.callbacks import CallbackManager
from mcpdb.agent.state import AgentState
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
        assert isinstance(result, str)
        assert len(result) > 0


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
        # Blueprint
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
            # Investigation 1 plan
            (
                {"analysis": "A", "approach": "B", "steps": []},
                {"input_tokens": 50, "output_tokens": 50},
            ),
            # Investigation 1 validate
            (
                {"adequate": True, "reasoning": "ok"},
                {"input_tokens": 50, "output_tokens": 20},
            ),
            # Investigation 2 plan
            (
                {"analysis": "A", "approach": "B", "steps": []},
                {"input_tokens": 50, "output_tokens": 50},
            ),
            # Investigation 2 validate
            (
                {"adequate": True, "reasoning": "ok"},
                {"input_tokens": 50, "output_tokens": 20},
            ),
            # Reasoning
            (
                {"sufficient": True, "skip_ids": [], "new_investigations": [], "reasoning": "Done"},
                {"input_tokens": 100, "output_tokens": 50},
            ),
        ]

        # Synthesis and investigation responses
        mock_llm.generate.side_effect = [
            ("Churn rate is 15%.", {"input_tokens": 50, "output_tokens": 30}),
            ("Enterprise: 5%, SMB: 25%.", {"input_tokens": 50, "output_tokens": 30}),
            ("# Report\n\nChurn analysis complete.", {"input_tokens": 200, "output_tokens": 300}),
        ]

        state = await run_deep(
            base_state, mock_llm, callbacks, mock_registry,
        )

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
        # Return many investigations
        mock_llm.generate_json.side_effect = [
            # Blueprint
            (
                {
                    "research_goal": "Big research",
                    "investigations": [
                        {"id": i, "question": f"Q{i}?", "approach": "SQL", "priority": "medium"}
                        for i in range(20)  # More than max_iterations
                    ],
                },
                {"input_tokens": 100, "output_tokens": 200},
            ),
        ] + [
            # Investigation plans (will be called for each)
            ({"analysis": "A", "approach": "B", "steps": []}, {"input_tokens": 50, "output_tokens": 50}),
        ] * 10 + [
            # Validates
            ({"adequate": True, "reasoning": "ok"}, {"input_tokens": 50, "output_tokens": 20}),
        ] * 10 + [
            # Reasoning (never sufficient)
            ({"sufficient": False, "skip_ids": [], "new_investigations": [], "reasoning": "More"}, {"input_tokens": 50, "output_tokens": 50}),
        ] * 10

        mock_llm.generate.side_effect = [
            (f"Result {i}", {"input_tokens": 50, "output_tokens": 30})
            for i in range(30)
        ]

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
            # Investigation plan
            ({"analysis": "A", "approach": "B", "steps": []}, {"input_tokens": 50, "output_tokens": 50}),
            # Validate
            ({"adequate": True, "reasoning": "ok"}, {"input_tokens": 50, "output_tokens": 20}),
            # Reasoning
            ({"sufficient": True, "skip_ids": [], "new_investigations": [], "reasoning": "Done"}, {"input_tokens": 50, "output_tokens": 50}),
        ]
        mock_llm.generate.side_effect = [
            ("Investigation result", {"input_tokens": 50, "output_tokens": 30}),
            ("Final report", {"input_tokens": 200, "output_tokens": 200}),
        ]

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
