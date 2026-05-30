from __future__ import annotations

import json
from typing import Any, Literal

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


class RunAgentTeamArgs(BaseModel):
    team_id: str = Field(..., min_length=1)
    max_concurrency: int = Field(default=4, ge=1, le=16)


class AgentTeamStatusArgs(BaseModel):
    team_run_id: str = Field(..., min_length=1)


class CancelAgentTeamRunArgs(BaseModel):
    team_run_id: str = Field(..., min_length=1)
    reason: str = ""


class AgentWorkflowStatusArgs(BaseModel):
    workflow_run_id: str = Field(..., min_length=1)


class CancelAgentWorkflowRunArgs(BaseModel):
    workflow_run_id: str = Field(..., min_length=1)
    reason: str = ""


class RerunFailedWorkflowPhaseArgs(BaseModel):
    workflow_run_id: str = Field(..., min_length=1)
    phase_run_id: str = Field(..., min_length=1)


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
    from ..workers.context import parent_metadata_from_runtime_context

    parent_metadata = parent_metadata_from_runtime_context(context)
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
        from ..subagents.orchestrator import run_delegate_task

        return json.dumps(
            run_delegate_task(
                task=task,
                target_agent=target_agent,
                reason=reason,
                session_id=session_id,
                parent_run_id=parent_run_id,
                approval_id=str(context.get("approval_id") or "unrestricted"),
                agent_id=str(context.get("agent_id") or "default"),
                parent_metadata=parent_metadata,
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
    from ..workers.context import parent_metadata_from_runtime_context

    parent_metadata = parent_metadata_from_runtime_context(context)
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
            **parent_metadata,
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


@tool(args_schema=RunAgentTeamArgs)
def run_agent_team(team_id: str, max_concurrency: int = 4) -> str:
    """Start an agent team run and return a polling handle."""

    context = runtime_context()
    if not context.get("approval_granted"):
        return json.dumps(
            {
                "status": "queued",
                "team_id": team_id,
                "team_run_id": "",
                "summary": "Agent team execution is queued for approval.",
            },
            ensure_ascii=False,
            default=str,
        )
    session_id = str(context.get("session_id") or "")
    parent_run_id = _context_run_id(context)
    if not session_id or not parent_run_id:
        raise ValueError("session_id and run_id are required to run an agent team")

    store = get_agent_store()
    team = store.agent_teams.get(team_id)
    if team is None:
        raise ValueError(f"unknown team: {team_id}")
    team_run = store.agent_team_runs.create(
        team_id=team_id,
        parent_session_id=session_id,
        parent_run_id=parent_run_id,
        approval_id=str(context.get("approval_id") or ""),
        goal=team["goal"],
        metadata={"source": "tool", "max_concurrency": max_concurrency},
    )
    _enqueue_team_run(store, team_run["id"], max_concurrency=max_concurrency)
    return json.dumps(
        {
            "status": store.agent_team_runs.get(team_run["id"])["status"],
            "team_id": team_id,
            "team_run_id": team_run["id"],
            "summary": "Agent team run enqueued.",
        },
        ensure_ascii=False,
        default=str,
    )


@tool(args_schema=AgentTeamStatusArgs)
def get_agent_team_status(team_run_id: str) -> str:
    """Read agent team run status."""

    store = get_agent_store()
    team_run = store.agent_team_runs.get(team_run_id)
    if team_run is None:
        raise ValueError(f"unknown team run: {team_run_id}")
    tasks = store.agent_team_tasks.list_for_team(team_run["team_id"])
    return json.dumps(
        {
            "status": team_run["status"],
            "team_id": team_run["team_id"],
            "team_run_id": team_run_id,
            "summary": team_run["summary"],
            "tasks": [
                {
                    "id": task["id"],
                    "title": task["title"],
                    "status": task["status"],
                    "subagent_run_id": task["result_subagent_id"],
                }
                for task in tasks
            ],
        },
        ensure_ascii=False,
        default=str,
    )


@tool(args_schema=CancelAgentTeamRunArgs)
def cancel_agent_team_run(team_run_id: str, reason: str = "") -> str:
    """Cancel a running or queued agent team run."""

    context = runtime_context()
    if not context.get("approval_granted"):
        return json.dumps(
            {
                "status": "queued",
                "team_run_id": team_run_id,
                "summary": "Agent team cancellation is queued for approval.",
            },
            ensure_ascii=False,
            default=str,
        )
    store = get_agent_store()
    cancelled = _background_queue(store).cancel(team_run_id, reason=reason)
    store.agent_team_runs.update(
        team_run_id,
        status="cancelled",
        metadata_patch={"cancel_reason": reason},
        finished=True,
    )
    return json.dumps(
        {"status": "cancelled", "team_run_id": team_run_id, "active_cancelled": cancelled},
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
    from ..workers.context import parent_metadata_from_runtime_context

    parent_metadata = parent_metadata_from_runtime_context(context)
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

    from ..workflows import load_workflow_spec_text

    spec = load_workflow_spec_text(workflow_yaml)
    store = get_agent_store()
    store.workflow_specs.upsert(
        spec_id=spec.id,
        name=spec.name,
        description=spec.description,
        spec=spec.as_dict(),
        metadata=spec.metadata,
    )
    run = store.workflow_runs.create(
        spec_id=spec.id,
        parent_session_id=session_id,
        parent_run_id=parent_run_id,
        inputs=dict(inputs or {}),
        metadata={**parent_metadata, "workflow_yaml": workflow_yaml},
    )
    _enqueue_workflow_run(
        store,
        run["id"],
        workflow_yaml=workflow_yaml,
        inputs=dict(inputs or {}),
        parent_metadata=parent_metadata,
    )
    return json.dumps(
        {
            "status": store.workflow_runs.get(run["id"])["status"],
            "workflow_run_id": run["id"],
            "summary": "Agent workflow run enqueued.",
            "child_run_references": [],
        },
        ensure_ascii=False,
        default=str,
    )


@tool(args_schema=AgentWorkflowStatusArgs)
def get_agent_workflow_status(workflow_run_id: str) -> str:
    """Read agent workflow run status."""

    store = get_agent_store()
    run = store.workflow_runs.get(workflow_run_id)
    if run is None:
        raise ValueError(f"unknown workflow run: {workflow_run_id}")
    phases = store.workflow_phase_runs.list_for_run(workflow_run_id)
    workers = store.workflow_worker_runs.list_for_run(workflow_run_id)
    return json.dumps(
        {
            "status": run["status"],
            "workflow_run_id": workflow_run_id,
            "summary": run["summary"],
            "phases": [
                {"id": phase["id"], "phase_id": phase["phase_id"], "status": phase["status"]}
                for phase in phases
            ],
            "workers": [
                {
                    "id": worker["id"],
                    "phase_run_id": worker["phase_run_id"],
                    "status": worker["status"],
                    "subagent_run_id": worker["subagent_run_id"],
                }
                for worker in workers
            ],
        },
        ensure_ascii=False,
        default=str,
    )


@tool(args_schema=CancelAgentWorkflowRunArgs)
def cancel_agent_workflow_run(workflow_run_id: str, reason: str = "") -> str:
    """Cancel a running or queued agent workflow run."""

    context = runtime_context()
    if not context.get("approval_granted"):
        return json.dumps(
            {
                "status": "queued",
                "workflow_run_id": workflow_run_id,
                "summary": "Agent workflow cancellation is queued for approval.",
            },
            ensure_ascii=False,
            default=str,
        )
    store = get_agent_store()
    cancelled = _background_queue(store).cancel(workflow_run_id, reason=reason)
    store.workflow_runs.update(
        workflow_run_id,
        status="stopped",
        metadata_patch={"cancel_reason": reason},
        finished=True,
    )
    return json.dumps(
        {"status": "stopped", "workflow_run_id": workflow_run_id, "active_cancelled": cancelled},
        ensure_ascii=False,
        default=str,
    )


@tool(args_schema=RerunFailedWorkflowPhaseArgs)
def rerun_failed_workflow_phase(workflow_run_id: str, phase_run_id: str) -> str:
    """Record a request to rerun a failed workflow phase."""

    context = runtime_context()
    if not context.get("approval_granted"):
        return json.dumps(
            {
                "status": "queued",
                "workflow_run_id": workflow_run_id,
                "phase_run_id": phase_run_id,
                "summary": "Workflow phase rerun is queued for approval.",
            },
            ensure_ascii=False,
            default=str,
        )
    store = get_agent_store()
    phase = store.workflow_phase_runs.get(phase_run_id)
    if phase is None or phase["workflow_run_id"] != workflow_run_id:
        raise ValueError(f"unknown phase run: {phase_run_id}")
    run = store.workflow_runs.get(workflow_run_id)
    if run is None:
        raise ValueError(f"unknown workflow run: {workflow_run_id}")
    workflow_yaml = str((run.get("metadata") or {}).get("workflow_yaml") or "")
    if not workflow_yaml:
        raise ValueError("workflow run does not contain workflow_yaml metadata")
    store.workflow_phase_runs.update(phase_run_id, status="queued", outputs=[])
    store.workflow_runs.update(
        workflow_run_id,
        status="queued",
        summary="Workflow phase rerun queued.",
        metadata_patch={"rerun_phase_run_id": phase_run_id},
    )
    _enqueue_workflow_run(
        store,
        workflow_run_id,
        workflow_yaml=workflow_yaml,
        inputs=dict(run.get("inputs") or {}),
        parent_metadata=dict(run.get("metadata") or {}),
    )
    return json.dumps(
        {
            "status": "queued",
            "workflow_run_id": workflow_run_id,
            "phase_run_id": phase_run_id,
        },
        ensure_ascii=False,
        default=str,
    )


def _context_run_id(context: dict[str, object]) -> str:
    metadata = context.get("metadata") if isinstance(context.get("metadata"), dict) else {}
    return str(context.get("run_id") or metadata.get("run_id") or "")


def _background_queue(store=None):
    from ..runtime.background_tasks import BackgroundRunQueue

    global _BACKGROUND_QUEUE
    try:
        return _BACKGROUND_QUEUE
    except NameError:
        active_store = store or get_agent_store()
        _BACKGROUND_QUEUE = BackgroundRunQueue(
            status_writer=lambda run_id, status, metadata: _write_background_status(
                active_store,
                run_id,
                status,
                metadata,
            ),
            orphan_provider=lambda: _running_background_rows(active_store),
        )
        _BACKGROUND_QUEUE.mark_orphans_interrupted()
        return _BACKGROUND_QUEUE


def _write_background_status(
    store,
    run_id: str,
    status: str,
    metadata: dict[str, Any],
) -> None:
    metadata_patch = {
        key: value
        for key, value in metadata.items()
        if key not in {"run_id", "kind", "status"}
    }
    if run_id.startswith("team-run-"):
        store.agent_team_runs.update(run_id, status=status, metadata_patch=metadata_patch)
        return
    if run_id.startswith("workflow-"):
        workflow_status = "stopped" if status in {"cancelled", "interrupted"} else status
        store.workflow_runs.update(run_id, status=workflow_status, metadata_patch=metadata_patch)


def _running_background_rows(store) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend({**row, "kind": "team"} for row in store.agent_team_runs.list_running())
    rows.extend({**row, "kind": "workflow"} for row in store.workflow_runs.list_running())
    return rows


def _enqueue_team_run(store, team_run_id: str, *, max_concurrency: int) -> None:
    from ..teams import TeamRuntime

    async def run(token):
        return await TeamRuntime(store, max_concurrency=max_concurrency).run(
            team_run_id,
            cancellation_token=token,
        )

    _background_queue(store).enqueue(team_run_id, "team", run)


def _enqueue_workflow_run(
    store,
    workflow_run_id: str,
    *,
    workflow_yaml: str,
    inputs: dict[str, object],
    parent_metadata: dict[str, object],
) -> None:
    from ..workflows import WorkflowRuntime, load_workflow_spec_text

    spec = load_workflow_spec_text(workflow_yaml)
    run = store.workflow_runs.get(workflow_run_id)
    if run is None:
        return

    async def execute(token):
        return await WorkflowRuntime(store).run(
            spec,
            parent_session_id=run["parent_session_id"],
            parent_run_id=run["parent_run_id"],
            inputs=dict(inputs or {}),
            parent_metadata=dict(parent_metadata or {}),
            workflow_run_id=workflow_run_id,
            cancellation_token=token,
        )

    _background_queue(store).enqueue(workflow_run_id, "workflow", execute)
