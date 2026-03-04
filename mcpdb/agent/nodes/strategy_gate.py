"""Strategy gate — pause execution for user decision on expensive queries."""

from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Any

from mcpdb.agent.state import AgentState
from mcpdb.agent.callbacks import CallbackManager

logger = logging.getLogger("mcpdb.agent.strategy_gate")

# TTL for pending strategies (10 minutes)
STRATEGY_TTL_SECONDS = 600


@dataclass
class PendingStrategy:
    """A saved agent state awaiting user strategy choice."""
    state: AgentState
    callbacks: CallbackManager
    created_at: float = field(default_factory=time.time)
    session_id: str = "default"


# In-memory store for pending strategies (one per session)
_pending_strategies: dict[str, PendingStrategy] = {}
_lock = threading.Lock()


def save_pending_strategy(
    session_id: str,
    state: AgentState,
    callbacks: CallbackManager,
) -> None:
    """Save agent state pending a user strategy choice."""
    with _lock:
        _pending_strategies[session_id] = PendingStrategy(
            state=state,
            callbacks=callbacks,
            session_id=session_id,
        )


def get_pending_strategy(session_id: str) -> PendingStrategy | None:
    """Retrieve a pending strategy, checking TTL."""
    with _lock:
        pending = _pending_strategies.get(session_id)
        if pending is None:
            return None
        if time.time() - pending.created_at > STRATEGY_TTL_SECONDS:
            del _pending_strategies[session_id]
            return None
        return pending


def consume_pending_strategy(session_id: str) -> PendingStrategy | None:
    """Retrieve and remove a pending strategy."""
    with _lock:
        pending = _pending_strategies.pop(session_id, None)
        if pending is None:
            return None
        if time.time() - pending.created_at > STRATEGY_TTL_SECONDS:
            return None
        return pending


def clear_pending_strategies() -> None:
    """Clear all pending strategies."""
    with _lock:
        _pending_strategies.clear()


async def strategy_gate(
    state: AgentState,
    callbacks: CallbackManager,
    session_id: str = "default",
) -> AgentState:
    """Strategy gate node — pause if cost analysis requires user input.

    If cost_analysis.decision is "recommended" or "necessary",
    save state and emit a strategy_request event.
    """
    cost_analysis = state.get("cost_analysis", {})
    decision = cost_analysis.get("decision", "not_required")

    if decision == "not_required":
        callbacks.emit("strategy_gate/pass")
        return state

    # Save state for later resumption
    save_pending_strategy(session_id, state, callbacks)

    callbacks.emit(
        "strategy_gate/awaiting",
        decision=decision,
        analyses=cost_analysis.get("analyses", []),
    )

    # Set state to indicate we're waiting
    state["optimization_state"] = "awaiting_strategy"
    state["response"] = (
        "This query may be expensive. Please choose a strategy:\n"
        "- **SAMPLE**: Run on a sample of the data (fast, approximate)\n"
        "- **FULL**: Run the full query (slow, exact)\n"
        "- **CANCEL**: Cancel this query\n\n"
        f"Reason: {cost_analysis.get('analyses', [{}])[0].get('reason', 'Potentially expensive query')}\n\n"
        "Use `submit_strategy` to continue."
    )

    return state
