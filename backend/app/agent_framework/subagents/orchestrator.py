"""Subagent orchestration entry points."""

from __future__ import annotations

from typing import Any

from ..storage import get_agent_store
from ..tool_runtime import ToolRegistry
from .delegate import SubagentDelegator, SubagentResult
from .merger import BestOfNMerger
from .roles import list_role_ids, registry_for_role


def create_subagent_registry(role_id: str = "researcher") -> ToolRegistry:
    """Return the bounded registry for a subagent role."""

    return registry_for_role(role_id)


def _normalize_role(target_agent: str | None) -> str:
    if target_agent and target_agent in list_role_ids():
        return target_agent
    return "researcher"


def run_delegate_task(
    *,
    task: str,
    target_agent: str,
    reason: str,
    session_id: str,
    parent_run_id: str,
    approval_id: str,
    agent_id: str = "default",
    n_attempts: int = 1,
) -> dict[str, Any]:
    """Run a bounded read-only subagent and return the merged result."""

    role_id = _normalize_role(target_agent)
    store = get_agent_store()
    delegator = SubagentDelegator(store)

    if n_attempts > 1:
        merger = BestOfNMerger(store, delegator)
        merged = merger.run(
            task=task,
            role_id=role_id,
            parent_session_id=session_id,
            parent_run_id=parent_run_id,
            n=n_attempts,
            reason=reason,
            agent_id=agent_id,
            approval_id=approval_id,
        )
        winner: SubagentResult | None = merged.winner
        return {
            "status": merged.status,
            "target_agent": role_id,
            "thread_id": winner.child_session_id if winner else "",
            "parent_session_id": session_id,
            "parent_run_id": parent_run_id,
            "approval_id": approval_id,
            "result": merged.final_response,
            "score": merged.score,
            "attempts": [
                {
                    "subagent_id": attempt.subagent_id,
                    "child_session_id": attempt.child_session_id,
                    "status": attempt.status,
                    "score": attempt.score,
                }
                for attempt in merged.attempts
            ],
        }

    result = delegator.dispatch(
        task=task,
        role_id=role_id,
        parent_session_id=session_id,
        parent_run_id=parent_run_id,
        agent_id=agent_id,
        reason=reason,
        approval_id=approval_id,
    )
    return {
        "status": result.status,
        "target_agent": role_id,
        "thread_id": result.child_session_id,
        "parent_session_id": session_id,
        "parent_run_id": parent_run_id,
        "approval_id": approval_id,
        "result": result.final_response,
        "score": result.score,
    }
