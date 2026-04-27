"""SubagentDelegator — runs one bounded subagent attempt.

The delegator owns the parent ↔ child wiring:

- Allocates a child session linked to the parent via metadata and the
  ``subagent_runs`` table.
- Builds a role-bound :class:`ToolRegistry` (scoped tool permissions).
- Executes a ``runner`` callable (real LangGraph by default; injectable
  for tests) and persists the final response and status.

The runner is injectable so unit tests don't need a live LLM. The
default runner builds the production LangGraph but can be swapped in
tests for deterministic ``fake`` runners.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from ..store import PostgresAgentStore
from ..tools import ToolRegistry
from .roles import SubagentRole, get_role, registry_for_role


@dataclass
class SubagentResult:
    subagent_id: str
    child_session_id: str
    role: str
    status: str
    final_response: str
    score: float = 0.0
    citations_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


SubagentRunner = Callable[
    [str, ToolRegistry, SubagentRole, dict[str, Any]],
    dict[str, Any],
]
"""Callable that drives a subagent attempt to completion.

Inputs:

- ``prompt`` — fully assembled task prompt for the subagent.
- ``registry`` — bounded tool registry.
- ``role`` — :class:`SubagentRole` spec.
- ``thread_config`` — LangGraph thread config (``{"configurable": {...}}``).

Returns a dict with at least ``final_response: str`` and optionally
``messages``, ``intermediate_steps``, and ``status``.
"""


_CITATION_RX = re.compile(r"https?://\S+|\[[^\]]+\]\([^)]+\)")


def _build_prompt(*, role: SubagentRole, task: str, reason: str) -> str:
    return (
        f"{role.system_prompt}\n\n"
        f"Reason for delegation: {reason or 'not specified'}\n\n"
        f"Task:\n{task}"
    )


def default_subagent_runner(
    prompt: str,
    registry: ToolRegistry,
    role: SubagentRole,
    thread_config: dict[str, Any],
) -> dict[str, Any]:
    """Production runner: real LangGraph + Postgres checkpointer."""

    from ..agent import build_agent_graph
    from ..checkpointing import create_checkpointer

    graph = build_agent_graph(registry=registry, checkpointer=create_checkpointer())
    state = graph.invoke(
        {
            "session_id": str(thread_config.get("configurable", {}).get("thread_id", "")),
            "agent_id": "default",
            "metadata": {
                "subagent_role": role.id,
                "budget": {
                    "max_turns": role.max_turns,
                    "max_wall_seconds": role.max_wall_seconds,
                },
            },
            "messages": [HumanMessage(content=prompt)],
        },
        config=thread_config,
    )
    final = ""
    for message in reversed(state.get("messages", [])):
        if isinstance(message, AIMessage) and message.content:
            final = str(message.content)
            break
    return {
        "final_response": final,
        "messages": state.get("messages", []),
        "intermediate_steps": state.get("intermediate_steps", []),
        "status": "completed",
    }


class SubagentDelegator:
    def __init__(
        self,
        store: PostgresAgentStore,
        *,
        runner: SubagentRunner | None = None,
    ) -> None:
        self.store = store
        self._runner = runner or default_subagent_runner

    def dispatch(
        self,
        *,
        task: str,
        role_id: str,
        parent_session_id: str,
        parent_run_id: str,
        agent_id: str = "default",
        reason: str = "",
        attempt_index: int = 0,
        approval_id: str = "",
    ) -> SubagentResult:
        role = get_role(role_id)

        if self.store.run_stop_requested(
            session_id=parent_session_id, run_id=parent_run_id
        ):
            return SubagentResult(
                subagent_id="",
                child_session_id="",
                role=role.id,
                status="stopped",
                final_response="",
            )

        child_session_id = self.store.create_session(
            agent_id=agent_id,
            title=f"sub:{role.id}:{parent_session_id[:8]}",
            metadata={
                "subagent": True,
                "role": role.id,
                "parent_session_id": parent_session_id,
                "parent_run_id": parent_run_id,
                "approval_id": approval_id,
                "attempt_index": attempt_index,
            },
        )

        record = self.store.subagent_runs.create(
            parent_session_id=parent_session_id,
            parent_run_id=parent_run_id,
            child_session_id=child_session_id,
            role=role.id,
            task=task,
            attempt_index=attempt_index,
            metadata={
                "approval_id": approval_id,
                "reason": reason,
                "tool_scope": list(role.tool_names),
            },
            status="running",
        )

        registry = registry_for_role(role.id)
        prompt = _build_prompt(role=role, task=task, reason=reason)
        thread_config = {"configurable": {"thread_id": child_session_id}}

        try:
            result = self._runner(prompt, registry, role, thread_config)
        except Exception as exc:  # noqa: BLE001 — surface the failure on the row.
            self.store.subagent_runs.update(
                record["id"],
                status="failed",
                final_response=f"runner error: {exc}",
                finished=True,
            )
            return SubagentResult(
                subagent_id=record["id"],
                child_session_id=child_session_id,
                role=role.id,
                status="failed",
                final_response=f"runner error: {exc}",
            )

        final = str(result.get("final_response") or "")
        citations = len(_CITATION_RX.findall(final))
        status = str(result.get("status") or "completed")

        from .merger import score_response

        score = score_response(final, citations_count=citations)
        self.store.subagent_runs.update(
            record["id"],
            status=status,
            score=score,
            final_response=final,
            metadata_patch={
                "citations_count": citations,
                "response_chars": len(final),
            },
            finished=True,
        )
        return SubagentResult(
            subagent_id=record["id"],
            child_session_id=child_session_id,
            role=role.id,
            status=status,
            final_response=final,
            score=score,
            citations_count=citations,
            metadata={"tool_scope": list(role.tool_names)},
        )
