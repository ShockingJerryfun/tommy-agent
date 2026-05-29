from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Coroutine
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ..prompt_context import merge_context_pact
from ..skills_forge.catalog import SkillCatalog, SkillProposal
from ..storage import get_agent_store
from .context import runtime_context


class SkillProposeArgs(BaseModel):
    name: str = Field(..., min_length=1, description="Human-readable skill name.")
    action: Literal["create", "update"] = "create"
    rationale: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    relative_path: str | None = None
    risks: list[str] = Field(default_factory=list)
    allow_auto_apply: bool = False


class ContextPactUpdateArgs(BaseModel):
    summary: str | None = None
    goals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    active_skills: list[str] = Field(default_factory=list)


class DelegateTaskArgs(BaseModel):
    task: str = Field(..., min_length=1)
    target_agent: str = "researcher"
    reason: str = ""


class TeamMemberToolSpec(BaseModel):
    role: str = Field(..., min_length=1)
    agent_definition_id: str | None = None


class TeamTaskToolSpec(BaseModel):
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    assigned_role: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    priority: int = 0


class CreateAgentTeamArgs(BaseModel):
    goal: str = Field(..., min_length=1)
    members: list[TeamMemberToolSpec] = Field(..., min_length=1)
    tasks: list[TeamTaskToolSpec] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class RunAgentWorkflowArgs(BaseModel):
    workflow_yaml: str = Field(..., min_length=1)
    inputs: dict[str, object] = Field(default_factory=dict)


@tool(args_schema=SkillProposeArgs)
def skill_propose(
    name: str,
    action: Literal["create", "update"] = "create",
    rationale: str = "",
    content: str = "",
    relative_path: str | None = None,
    risks: list[str] | None = None,
    allow_auto_apply: bool = False,
) -> str:
    """Create a reviewable skill proposal."""
    context = runtime_context()
    agent_id = str(context.get("agent_id") or "default")
    metadata = dict(context.get("metadata") or {})
    catalog = SkillCatalog(agent_id=agent_id)
    result = catalog.create_proposal(
        SkillProposal(
            name=name,
            action=action,
            rationale=rationale,
            content=content,
            relative_path=relative_path,
            risks=risks or [],
            metadata={"source": "agent_tool", "session_id": context.get("session_id")},
        ),
        allow_auto_apply=bool(allow_auto_apply or metadata.get("allow_auto_apply")),
    )
    return json.dumps(result, ensure_ascii=False, default=str)


@tool(args_schema=ContextPactUpdateArgs)
def context_pact_update(
    summary: str | None = None,
    goals: list[str] | None = None,
    constraints: list[str] | None = None,
    facts: list[str] | None = None,
    open_questions: list[str] | None = None,
    active_skills: list[str] | None = None,
) -> str:
    """Merge durable session context into the current context pact."""
    context = runtime_context()
    session_id = str(context.get("session_id") or "")
    if not session_id:
        raise ValueError("session_id is required for context pact updates.")
    agent_id = str(context.get("agent_id") or "default")
    store = get_agent_store()
    patch = {
        "summary": summary,
        "goals": goals or [],
        "constraints": constraints or [],
        "facts": facts or [],
        "open_questions": open_questions or [],
        "active_skills": active_skills or [],
    }
    pact = merge_context_pact(
        store.get_context_pact(session_id, agent_id=agent_id),
        {key: value for key, value in patch.items() if value},
    )
    store.upsert_context_pact(session_id, agent_id=agent_id, pact=pact)
    return json.dumps({"session_id": session_id, "pact": pact}, ensure_ascii=False, default=str)


@tool(args_schema=DelegateTaskArgs)
def delegate_task(task: str, target_agent: str = "researcher", reason: str = "") -> str:
    """Record or execute a bounded delegation request."""
    context = runtime_context()
    if context.get("approval_granted"):
        session_id = str(context.get("session_id") or "")
        parent_run_id = str((context.get("metadata") or {}).get("run_id") or "")
        if get_agent_store().explicit_stop_requested(session_id=session_id, run_id=parent_run_id):
            return json.dumps(
                {
                    "status": "stopped",
                    "target_agent": target_agent,
                    "session_id": session_id,
                    "parent_run_id": parent_run_id,
                    "message": "Delegation was not started because the run was stopped.",
                },
                ensure_ascii=False,
                default=str,
            )
        from ..orchestrator import run_delegate_task

        return json.dumps(
            run_delegate_task(
                task=task,
                target_agent=target_agent,
                reason=reason,
                session_id=session_id,
                parent_run_id=parent_run_id,
                approval_id=str(context.get("approval_id") or "unrestricted"),
                agent_id=str(context.get("agent_id") or "default"),
            ),
            ensure_ascii=False,
            default=str,
        )

    return json.dumps(
        {
            "status": "queued",
            "target_agent": target_agent,
            "task": task,
            "reason": reason,
            "session_id": context.get("session_id"),
            "note": (
                "Delegation is recorded for orchestration; "
                "the main LangGraph agent remains in control."
            ),
        },
        ensure_ascii=False,
        default=str,
    )


@tool(args_schema=CreateAgentTeamArgs)
def create_agent_team(
    goal: str,
    members: list[TeamMemberToolSpec],
    tasks: list[TeamTaskToolSpec] | None = None,
    metadata: dict[str, str] | None = None,
) -> str:
    """Create a lead-controlled agent team with optional queued tasks."""

    context = runtime_context()
    if not context.get("approval_granted"):
        return json.dumps(
            {
                "status": "queued",
                "team_id": "",
                "summary": "Agent team creation is queued for approval.",
                "child_run_references": [],
            },
            ensure_ascii=False,
            default=str,
        )

    session_id = str(context.get("session_id") or "")
    parent_run_id = _context_run_id(context)
    if not session_id or not parent_run_id:
        raise ValueError("session_id and run_id are required to create an agent team")

    from ..teams import TeamService

    store = get_agent_store()
    service = TeamService(store)
    team = service.create_team(
        parent_session_id=session_id,
        parent_run_id=parent_run_id,
        goal=goal,
        members=[
            {
                "role": member.role,
                "agent_definition_id": member.agent_definition_id or member.role,
            }
            for member in members
        ],
        metadata={
            **(metadata or {}),
            "approval_id": str(context.get("approval_id") or ""),
            "source": "tool",
        },
    )
    created_tasks = []
    for task in tasks or []:
        created_tasks.append(
            service.create_task(
                team["id"],
                title=task.title,
                description=task.description,
                assigned_role=task.assigned_role,
                dependencies=task.dependencies,
                priority=task.priority,
            )
        )

    return json.dumps(
        {
            "status": team["status"],
            "team_id": team["id"],
            "task_count": len(created_tasks),
            "summary": f"Created agent team for goal: {goal}",
            "child_run_references": [],
        },
        ensure_ascii=False,
        default=str,
    )


@tool(args_schema=RunAgentWorkflowArgs)
def run_agent_workflow(
    workflow_yaml: str,
    inputs: dict[str, object] | None = None,
) -> str:
    """Run a declarative YAML workflow through bounded worker agents."""

    context = runtime_context()
    if not context.get("approval_granted"):
        return json.dumps(
            {
                "status": "queued",
                "workflow_run_id": "",
                "summary": "Agent workflow execution is queued for approval.",
                "child_run_references": [],
            },
            ensure_ascii=False,
            default=str,
        )

    session_id = str(context.get("session_id") or "")
    parent_run_id = _context_run_id(context)
    if not session_id or not parent_run_id:
        raise ValueError("session_id and run_id are required to run an agent workflow")

    from ..workflows import WorkflowRuntime, load_workflow_spec_text

    spec = load_workflow_spec_text(workflow_yaml)
    result = _run_coro_sync(
        WorkflowRuntime(get_agent_store()).run(
            spec,
            parent_session_id=session_id,
            parent_run_id=parent_run_id,
            inputs=dict(inputs or {}),
        )
    )
    child_refs = [
        {
            "subagent_run_id": row["subagent_run_id"],
            "child_session_id": row["child_session_id"],
            "status": row["status"],
        }
        for row in get_agent_store().workflow_worker_runs.list_for_run(result.workflow_run_id)
    ]
    return json.dumps(
        {
            "status": result.status,
            "workflow_run_id": result.workflow_run_id,
            "summary": result.summary,
            "child_run_references": child_refs,
        },
        ensure_ascii=False,
        default=str,
    )


def _context_run_id(context: dict[str, object]) -> str:
    metadata = context.get("metadata") if isinstance(context.get("metadata"), dict) else {}
    return str(context.get("run_id") or metadata.get("run_id") or "")


def _run_coro_sync(coro: Coroutine[object, object, object]) -> object:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: object = None
    error: BaseException | None = None

    def run_in_thread() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - re-raised in caller thread.
            error = exc

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()
    thread.join()
    if error is not None:
        raise error
    return result
