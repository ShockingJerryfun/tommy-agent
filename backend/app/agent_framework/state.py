from __future__ import annotations

from typing import Any, Annotated

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


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    intermediate_steps: Annotated[list[dict[str, Any]], append_steps]
    extracted_context: Annotated[dict[str, Any], merge_context]
    session_id: str
    agent_id: str
    metadata: dict[str, Any]


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
    }
