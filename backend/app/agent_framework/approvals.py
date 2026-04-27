from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .tools import ToolRegistry

APPROVAL_REQUIRED_TOOLS = {"write_local_file", "run_shell_command", "delegate_task"}

DENIED_COMMAND_PATTERNS = (
    r"\brm\s+-[^;&|]*r[^;&|]*f\b",
    r"\bsudo\b",
    r"\bchmod\s+-R\b",
    r"\bchown\s+-R\b",
    r"\bmkfs\b",
    r"\bdiskutil\b",
    r"\bdd\s+if=",
    r":\(\)\s*\{",
    r"\bcurl\b.+\|\s*(sh|bash|zsh)",
    r"\bwget\b.+\|\s*(sh|bash|zsh)",
)


@dataclass(frozen=True)
class ApprovalDecision:
    needs_approval: bool
    risk_level: str = "low"
    summary: str = ""


def evaluate_tool_call(
    name: str,
    args: dict[str, Any],
    *,
    command_scope: str = "restricted",
) -> ApprovalDecision:
    if command_scope == "unrestricted":
        return ApprovalDecision(needs_approval=False)

    if name not in APPROVAL_REQUIRED_TOOLS:
        return ApprovalDecision(needs_approval=False)

    if name == "write_local_file":
        mode = str(args.get("mode") or "overwrite")
        path = str(args.get("path") or "")
        bytes_count = len(str(args.get("content") or "").encode("utf-8"))
        return ApprovalDecision(
            needs_approval=True,
            risk_level="high" if mode == "overwrite" else "medium",
            summary=f"写入文件 {path}（{mode}, {bytes_count} bytes）",
        )

    if name == "run_shell_command":
        command = str(args.get("command") or "")
        risk = "high" if command_is_dangerous(command) else "medium"
        return ApprovalDecision(
            needs_approval=True,
            risk_level=risk,
            summary=f"运行 shell 命令：{command[:180]}",
        )

    if name == "delegate_task":
        target = str(args.get("target_agent") or "researcher")
        task = str(args.get("task") or "")
        return ApprovalDecision(
            needs_approval=True,
            risk_level="medium",
            summary=f"委派给 {target}: {task[:180]}",
        )

    return ApprovalDecision(needs_approval=True, risk_level="medium", summary=name)


def command_is_dangerous(command: str) -> bool:
    normalized = " ".join(command.strip().split())
    return any(
        re.search(pattern, normalized, flags=re.IGNORECASE)
        for pattern in DENIED_COMMAND_PATTERNS
    )


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
