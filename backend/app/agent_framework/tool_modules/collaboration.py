from __future__ import annotations

import json
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
        if get_agent_store().run_stop_requested(session_id=session_id, run_id=parent_run_id):
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
