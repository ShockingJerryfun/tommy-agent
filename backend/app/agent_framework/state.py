"""AgentState v2 — typed graph state with cognitive scaffolding.

S3 introduces the cognitive graph (pre_run / planner / reasoner / actor /
critic / reflector). This module extends :class:`AgentState` with the
fields those nodes write/read, while keeping the dict shape strictly
back-compat: every new field is optional and defaults to a sensible
empty value, so callers from S0/S1/S2 keep working unchanged.

New fields
----------

``budget``
    Hard-cap accounting populated by ``pre_run`` and updated by every
    cognitive node. Shape: ``Budget.as_dict()``.

``plan``
    Lightweight plan written by the planner. Shape:
    ``{"summary": str, "steps": list[str], "expected_tools": list[str],
       "created_at": iso}``.

``loop_signals``
    Loop detector output. Shape: ``{"detected": bool, "reason": str,
       "repeated_call": dict | None, "count": int}``.

``drift_signals``
    Drift detector output. Shape: ``{"detected": bool, "reason": str,
       "tool_error_streak": int}``.

``critic_directives``
    Append-only list of directives the critic emits for the next agent
    turn. Each entry: ``{"kind": str, "message": str, "created_at": iso,
       "node": str}``.

``citation_signals``
    Citation enforcement output. Shape: ``{"required": bool,
       "satisfied": bool, "missing_for_tools": list[str]}``.

``reflection``
    Final reflector output. Shape: ``{"summary": str, "memory_proposals":
       list[dict], "created_at": iso}``.
"""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


def append_steps(
    left: list[dict[str, Any]] | None,
    right: list[dict[str, Any]] | dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Append intermediate step records without losing earlier graph updates."""
    if not left:
        left = []
    if right is None:
        return list(left)
    if isinstance(right, dict):
        return [*left, right]
    return [*left, *right]


def merge_context(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge extracted context defensively instead of replacing it per node."""
    merged = dict(left or {})
    for key, value in (right or {}).items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = merge_context(merged[key], value)
        else:
            merged[key] = value
    return merged


def merge_dict(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> dict[str, Any]:
    """Shallow merge with right-overrides-left semantics for top-level keys.

    Used for ``budget``, ``plan``, ``loop_signals``, ``drift_signals``,
    ``citation_signals`` and ``reflection``: each node carries forward
    the prior payload and rewrites the parts it owns, so a shallow merge
    keeps both per-key writes safe across concurrent updates.
    """

    if not left and not right:
        return {}
    merged = dict(left or {})
    for key, value in (right or {}).items():
        merged[key] = value
    return merged


def append_directives(
    left: list[dict[str, Any]] | None,
    right: list[dict[str, Any]] | dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Append-only reducer for critic directives."""
    return append_steps(left, right)


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    intermediate_steps: Annotated[list[dict[str, Any]], append_steps]
    extracted_context: Annotated[dict[str, Any], merge_context]
    session_id: str
    agent_id: str
    metadata: dict[str, Any]
    # --- v2 cognitive fields ---
    budget: Annotated[dict[str, Any], merge_dict]
    plan: Annotated[dict[str, Any], merge_dict]
    loop_signals: Annotated[dict[str, Any], merge_dict]
    drift_signals: Annotated[dict[str, Any], merge_dict]
    critic_directives: Annotated[list[dict[str, Any]], append_directives]
    citation_signals: Annotated[dict[str, Any], merge_dict]
    reflection: Annotated[dict[str, Any], merge_dict]


def initial_state(
    *,
    session_id: str,
    agent_id: str = "default",
    metadata: dict[str, Any] | None = None,
) -> AgentState:
    return {
        "messages": [],
        "intermediate_steps": [],
        "extracted_context": {},
        "session_id": session_id,
        "agent_id": agent_id,
        "metadata": metadata or {},
        "budget": {},
        "plan": {},
        "loop_signals": {},
        "drift_signals": {},
        "critic_directives": [],
        "citation_signals": {},
        "reflection": {},
    }
