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

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..storage import PostgresAgentStore
from ..tool_runtime import ToolRegistry
from .roles import SubagentRole

if TYPE_CHECKING:
    from ..workers.context import ChildRunContext


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


def default_subagent_runner(
    prompt: str,
    registry: ToolRegistry,
    role: SubagentRole,
    thread_config: dict[str, Any],
) -> dict[str, Any]:
    """Production runner: real LangGraph + Postgres checkpointer."""

    from ..workers.child_run_service import default_subagent_runner as run_child

    return run_child(prompt, registry, role, thread_config)


class SubagentDelegator:
    def __init__(
        self,
        store: PostgresAgentStore,
        *,
        runner: SubagentRunner | None = None,
    ) -> None:
        self.store = store
        self._runner = runner

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
        child_context: ChildRunContext | None = None,
        parent_metadata: dict[str, Any] | None = None,
    ) -> SubagentResult:
        if child_context is None:
            from ..workers.context import derive_child_context

            overrides = {"approval_id": approval_id} if approval_id else None
            child_context = derive_child_context(
                parent_session_id=parent_session_id,
                parent_run_id=parent_run_id,
                parent_agent_id=agent_id,
                parent_metadata=parent_metadata,
                role_id=role_id,
                overrides=overrides,
            )

        from ..workers.child_run_service import ChildRunRequest, ChildRunService

        worker_result = ChildRunService(self.store, runner=self._runner).run(
            ChildRunRequest(
                task=task,
                role_id=role_id,
                context=child_context,
                attempt_index=attempt_index,
                reason=reason,
            )
        )
        metadata = dict(worker_result.metadata or {})
        return SubagentResult(
            subagent_id=worker_result.subagent_id,
            child_session_id=worker_result.child_session_id,
            role=worker_result.role_id,
            status=worker_result.status,
            final_response=worker_result.final_response,
            score=worker_result.score,
            citations_count=int(metadata.get("citations_count") or 0),
            metadata=metadata,
        )
