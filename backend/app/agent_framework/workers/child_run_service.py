"""Single chokepoint for child-agent execution."""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from ..storage import PostgresAgentStore
from ..subagents.roles import SubagentRole, registry_for_role, resolve_role
from ..tool_runtime import ToolRegistry
from .context import ChildRunContext
from .types import WorkerResult

SubagentRunner = Callable[
    [str, ToolRegistry, SubagentRole, dict[str, Any]],
    dict[str, Any],
]


_CITATION_RX = re.compile(r"https?://\S+|\[[^\]]+\]\([^)]+\)")
_RECURSIVE_TOOL_NAMES = {
    "create_agent_workflow",
    "create_agent_team",
    "get_agent_team_status",
    "get_agent_workflow_status",
    "cancel_agent_team_run",
    "cancel_agent_workflow_run",
    "rerun_failed_workflow_phase",
    "run_agent_team",
    "run_agent_workflow",
}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChildRunRequest:
    task: str
    role_id: str
    context: ChildRunContext
    attempt_index: int = 0
    reason: str = ""
    task_id: str = ""


def default_subagent_runner(
    prompt: str,
    registry: ToolRegistry,
    role: SubagentRole,
    thread_config: dict[str, Any],
) -> dict[str, Any]:
    """Production runner: real LangGraph + Postgres checkpointer."""

    from ..agent import build_agent_graph
    from ..runtime.checkpointing import create_checkpointer

    metadata = dict(thread_config.get("metadata") or {})
    metadata["subagent_role"] = role.id
    metadata.setdefault(
        "budget",
        {
            "max_turns": role.max_turns,
            "max_wall_seconds": role.max_wall_seconds,
        },
    )
    graph = build_agent_graph(registry=registry, checkpointer=create_checkpointer())
    state = graph.invoke(
        {
            "session_id": str(thread_config.get("configurable", {}).get("thread_id", "")),
            "agent_id": str(metadata.get("parent_agent_id") or "default"),
            "metadata": metadata,
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


class ChildRunService:
    def __init__(
        self,
        store: PostgresAgentStore,
        *,
        runner: SubagentRunner | None = None,
    ) -> None:
        self.store = store
        self._runner = runner or default_subagent_runner

    def run(self, request: ChildRunRequest) -> WorkerResult:
        context = request.context
        if self.store.explicit_stop_requested(
            session_id=context.parent_session_id,
            run_id=context.parent_run_id,
        ):
            return WorkerResult(
                task_id=request.task_id,
                subagent_id="",
                child_session_id="",
                role_id=request.role_id,
                status="stopped",
                final_response="",
            )

        role = resolve_role(request.role_id, child_context=context)
        registry = registry_for_role(request.role_id, child_context=context)
        registry = _apply_recursion_guard(registry, context)
        metadata = _run_metadata(
            context=context,
            role=role,
            registry=registry,
            reason=request.reason,
            attempt_index=request.attempt_index,
        )
        child_session_id = self.store.create_session(
            agent_id=context.parent_agent_id,
            title=f"sub:{role.id}:{context.parent_session_id[:8]}",
            metadata={"subagent": True, "role": role.id, **metadata},
        )
        record = self.store.subagent_runs.create(
            parent_session_id=context.parent_session_id,
            parent_run_id=context.parent_run_id,
            child_session_id=child_session_id,
            role=role.id,
            task=request.task,
            attempt_index=request.attempt_index,
            metadata=metadata,
            status="running",
            role_id=role.id,
            agent_definition_id=role.id,
            team_id=context.team_id,
            team_run_id=str(metadata.get("team_run_id") or ""),
            team_task_id=context.team_task_id,
            workflow_run_id=context.workflow_run_id,
            phase_run_id=context.phase_run_id,
            workflow_phase_id=context.workflow_phase_id,
            approval_id=context.approval_id,
        )

        prompt = _build_prompt(role=role, task=request.task, reason=request.reason)
        _record_prompt_snapshot_best_effort(
            store=self.store,
            child_session_id=child_session_id,
            subagent_run_id=record["id"],
            context=context,
            role=role,
            prompt=prompt,
            metadata=metadata,
        )
        thread_config = {
            "configurable": {"thread_id": child_session_id},
            "metadata": metadata,
            "recursion_limit": max(32, int(role.max_turns) * 5),
        }
        try:
            result = self._runner(prompt, registry, role, thread_config)
        except Exception as exc:  # noqa: BLE001 - failures are persisted and returned.
            final_response = f"runner error: {exc}"
            self.store.subagent_runs.update(
                record["id"],
                status="failed",
                final_response=final_response,
                error_type=type(exc).__name__,
                error_message=str(exc),
                metadata_patch={"error_type": type(exc).__name__},
                finished=True,
            )
            return WorkerResult(
                task_id=request.task_id or record["id"],
                subagent_id=record["id"],
                child_session_id=child_session_id,
                role_id=role.id,
                status="failed",
                final_response=final_response,
                metadata={"error_type": type(exc).__name__},
            )

        final = str(result.get("final_response") or "")
        citations = len(_CITATION_RX.findall(final))
        score = _score_response(final, citations_count=citations)
        status = str(result.get("status") or "completed")
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
        return WorkerResult(
            task_id=request.task_id or record["id"],
            subagent_id=record["id"],
            child_session_id=child_session_id,
            role_id=role.id,
            status=status,
            final_response=final,
            score=score,
            metadata={
                **metadata,
                "citations_count": citations,
                "tool_scope": [tool.name for tool in registry.tools],
            },
        )


def _build_prompt(*, role: SubagentRole, task: str, reason: str) -> str:
    return (
        f"{role.system_prompt}\n\n"
        f"Reason for delegation: {reason or 'not specified'}\n\n"
        f"Task:\n{task}"
    )


def _record_prompt_snapshot(
    *,
    store: PostgresAgentStore,
    child_session_id: str,
    subagent_run_id: str,
    context: ChildRunContext,
    role: SubagentRole,
    prompt: str,
    metadata: dict[str, Any],
) -> None:
    store.record_prompt_snapshot(
        session_id=child_session_id,
        agent_id=context.parent_agent_id,
        run_id=subagent_run_id,
        model=str(metadata.get("model") or role.model or ""),
        total_chars=len(prompt),
        section_count=1,
        truncated_count=0,
        dropped_count=0,
        content_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        sections=[
            {
                "name": "subagent_task_prompt",
                "title": f"{role.title} Task Prompt",
                "source": "child_run_service",
                "priority": 100,
                "render_order": 10,
                "budget_chars": len(prompt),
                "min_chars": 0,
                "required": True,
                "char_count": len(prompt),
                "original_chars": len(prompt),
                "truncated": False,
                "dropped": False,
                "preview": prompt[:360].rstrip(),
            }
        ],
        budget={
            "requested_chars": len(prompt),
            "granted_chars": len(prompt),
            "max_chars": len(prompt),
            "section_count": 1,
            "truncated_count": 0,
            "dropped_count": 0,
        },
        metadata={
            "source": "child_run_service",
            "role_id": role.id,
            "subagent_role": context.subagent_role,
        },
        injections=None,
    )


def _record_prompt_snapshot_best_effort(
    *,
    store: PostgresAgentStore,
    child_session_id: str,
    subagent_run_id: str,
    context: ChildRunContext,
    role: SubagentRole,
    prompt: str,
    metadata: dict[str, Any],
) -> None:
    try:
        _record_prompt_snapshot(
            store=store,
            child_session_id=child_session_id,
            subagent_run_id=subagent_run_id,
            context=context,
            role=role,
            prompt=prompt,
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001 - prompt audit must not orphan child runs.
        logger.warning(
            "Unable to persist child prompt snapshot for subagent run %s: %s",
            subagent_run_id,
            exc,
        )


def _apply_recursion_guard(registry: ToolRegistry, context: ChildRunContext) -> ToolRegistry:
    if not context.is_child and context.depth <= 0:
        return registry
    return ToolRegistry(
        tools=tuple(
            tool
            for tool in registry.tools
            if not _is_recursive_spawning_tool(str(tool.name))
        )
    )


def _is_recursive_spawning_tool(name: str) -> bool:
    return (
        name in _RECURSIVE_TOOL_NAMES
        or name.startswith(
            (
                "create_agent_team",
                "create_agent_workflow",
                "get_agent_team_status",
                "get_agent_workflow_status",
                "cancel_agent_team_run",
                "cancel_agent_workflow_run",
                "rerun_failed_workflow_phase",
                "run_agent_team",
                "run_agent_workflow",
            )
        )
        or "agent_team" in name
        or "workflow" in name
    )


def _run_metadata(
    *,
    context: ChildRunContext,
    role: SubagentRole,
    registry: ToolRegistry,
    reason: str,
    attempt_index: int,
) -> dict[str, Any]:
    metadata = context.as_metadata()
    metadata.update(
        {
            "reason": reason,
            "attempt_index": attempt_index,
            "tool_scope": [tool.name for tool in registry.tools],
            "role_tool_names": list(role.tool_names),
            "role_permission_mode": role.permission_mode,
            "role_model": role.model,
        }
    )
    if not metadata.get("model") and role.model:
        metadata["model"] = role.model
    if not metadata.get("budget"):
        metadata["budget"] = {
            "max_turns": role.max_turns,
            "max_wall_seconds": role.max_wall_seconds,
        }
    return metadata


def _score_response(text: str, *, citations_count: int) -> float:
    if not text.strip():
        return 0.0
    length = len(text)
    length_score = min(length, 1200) / 1200.0
    citation_score = min(citations_count, 5) / 5.0
    return round(0.5 * length_score + 0.5 * citation_score, 4)
