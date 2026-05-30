"""Approval helpers backed by the tool permission policy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .catalog import ToolRegistry
from .permissions import default_permission_policy


@dataclass(frozen=True)
class ApprovalDecision:
    needs_approval: bool
    risk_level: str = "low"
    summary: str = ""
    denied: bool = False
    deny_reason: str = ""


def _approval_required_tools() -> set[str]:
    return default_permission_policy().approval_required_tool_names()


APPROVAL_REQUIRED_TOOLS = _approval_required_tools()


def _denied_command_patterns() -> tuple[str, ...]:
    return tuple(pattern.pattern for pattern in default_permission_policy().denied_command_patterns)


DENIED_COMMAND_PATTERNS = _denied_command_patterns()


def evaluate_tool_call(
    name: str,
    args: dict[str, Any],
    *,
    command_scope: str = "restricted",
) -> ApprovalDecision:
    decision = default_permission_policy().evaluate(name, args, command_scope=command_scope)
    return ApprovalDecision(
        needs_approval=decision.needs_approval,
        risk_level=decision.risk_level,
        summary=decision.summary,
        denied=decision.denied,
        deny_reason=decision.deny_reason,
    )


def command_is_dangerous(command: str) -> bool:
    return default_permission_policy().command_is_dangerous(command)


def assert_command_allowed(command: str) -> None:
    return None


def approval_pending_tool_message(approval: dict[str, Any]) -> str:
    return json.dumps(
        {
            "status": "pending_approval",
            "approval_id": approval["id"],
            "tool_name": approval["tool_name"],
            "summary": approval["summary"],
            "message": "This action has been queued for user approval.",
        },
        ensure_ascii=False,
    )


def execute_approved_action(
    approval: dict[str, Any],
    *,
    registry: ToolRegistry,
    context: dict[str, Any] | None = None,
) -> str:
    tool_name = str(approval["tool_name"])
    args = dict(approval.get("args") or {})
    runtime_context = {
        **(context or {}),
        "session_id": approval.get("session_id"),
        "run_id": approval.get("run_id"),
        "metadata": {"run_id": approval.get("run_id")},
        "approval_granted": True,
        "approval_id": approval.get("id"),
    }

    if tool_name == "delegate_task":
        from ..subagents import run_delegate_task
        from ..workers.context import parent_metadata_from_runtime_context

        result = run_delegate_task(
            task=str(args.get("task") or ""),
            target_agent=str(args.get("target_agent") or "researcher"),
            reason=str(args.get("reason") or ""),
            session_id=str(approval.get("session_id") or ""),
            parent_run_id=str(approval.get("run_id") or ""),
            approval_id=str(approval.get("id") or ""),
            agent_id=str((context or {}).get("agent_id") or "default"),
            parent_metadata=parent_metadata_from_runtime_context(runtime_context),
        )
        return json.dumps(result, ensure_ascii=False, default=str)

    return registry.invoke(tool_name, args, context=runtime_context)
