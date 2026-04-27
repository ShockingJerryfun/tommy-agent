"""Approval helpers — thin wrappers over the S4 permission policy.

Historically this module owned the hardcoded approval list and the
``DENIED_COMMAND_PATTERNS`` regex tuple. As of S4 the policy lives in
``tool_runtime/permissions.yaml`` and is consulted via
:func:`tool_runtime.default_permission_policy`. We keep the legacy
function names so call sites (action node, tests, API) can keep
importing them without churn while the new typed surface in
``tool_runtime`` becomes the load-bearing path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .tool_runtime import default_permission_policy
from .tools import ToolRegistry


@dataclass(frozen=True)
class ApprovalDecision:
    needs_approval: bool
    risk_level: str = "low"
    summary: str = ""


def _approval_required_tools() -> set[str]:
    policy = default_permission_policy()
    return {
        name
        for name, spec in policy._tools.items()  # noqa: SLF001 - intentional read
        if str(spec.get("approval") or "never") != "never"
    }


# Kept for back-compat with callers / tests that introspect the set directly.
APPROVAL_REQUIRED_TOOLS = _approval_required_tools()


def _denied_command_patterns() -> tuple[str, ...]:
    return tuple(
        pattern.pattern for pattern in default_permission_policy().denied_command_patterns
    )


# Mirrors the legacy module-level tuple so existing imports keep working.
DENIED_COMMAND_PATTERNS = _denied_command_patterns()


def evaluate_tool_call(
    name: str,
    args: dict[str, Any],
    *,
    command_scope: str = "restricted",
) -> ApprovalDecision:
    decision = default_permission_policy().evaluate(
        name, args, command_scope=command_scope
    )
    # Outright denials still surface as "needs_approval=True" in the legacy
    # contract; the action node escalates them as approval-pending so the
    # human reviewer can make the call. The structured ToolRuntime path
    # short-circuits to a permission_denied error instead.
    return ApprovalDecision(
        needs_approval=decision.needs_approval,
        risk_level=decision.risk_level,
        summary=decision.summary,
    )


def command_is_dangerous(command: str) -> bool:
    return default_permission_policy().command_is_dangerous(command)


def assert_command_allowed(command: str) -> None:
    if command_is_dangerous(command):
        raise PermissionError(f"Command rejected by safety policy: {command}")


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
        "approval_granted": True,
        "approval_id": approval.get("id"),
    }

    if tool_name == "run_shell_command":
        assert_command_allowed(str(args.get("command") or ""))

    if tool_name == "delegate_task":
        from .orchestrator import run_delegate_task

        result = run_delegate_task(
            task=str(args.get("task") or ""),
            target_agent=str(args.get("target_agent") or "researcher"),
            reason=str(args.get("reason") or ""),
            session_id=str(approval.get("session_id") or ""),
            parent_run_id=str(approval.get("run_id") or ""),
            approval_id=str(approval.get("id") or ""),
            agent_id=str((context or {}).get("agent_id") or "default"),
        )
        return json.dumps(result, ensure_ascii=False, default=str)

    return registry.invoke(tool_name, args, context=runtime_context)
