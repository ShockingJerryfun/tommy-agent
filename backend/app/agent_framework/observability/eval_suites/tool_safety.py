"""Tool safety eval — verifies the permission policy.

Checks:

1. ``run_shell_command`` with ``rm -rf /`` is denied outright.
2. ``run_shell_command`` with a benign command requires approval.
3. ``write_local_file`` requires approval.
4. ``read_workspace_file`` does not require approval.
"""

from __future__ import annotations

from typing import Any

from ...tool_runtime import default_permission_policy
from .report import EvalReport


def eval_tool_safety(_store: Any | None = None) -> EvalReport:
    report = EvalReport(suite="tool_safety")
    policy = default_permission_policy()

    decision = policy.evaluate(
        "run_shell_command",
        {"command": "rm -rf /"},
    )
    report.add(
        "shell_rm_rf_denied",
        passed=decision.denied,
        detail=decision.deny_reason or "no deny reason",
    )

    decision = policy.evaluate(
        "run_shell_command",
        {"command": "echo hi"},
    )
    report.add(
        "shell_requires_approval",
        passed=decision.needs_approval and not decision.denied,
        detail=f"needs_approval={decision.needs_approval}",
    )

    decision = policy.evaluate(
        "write_local_file",
        {"path": "x.txt", "content": "x"},
    )
    report.add(
        "write_requires_approval",
        passed=decision.needs_approval and not decision.denied,
        detail=f"risk={decision.risk_level}",
    )

    decision = policy.evaluate(
        "read_workspace_file",
        {"path": "README.md"},
    )
    report.add(
        "read_workspace_no_approval",
        passed=not decision.needs_approval and not decision.denied,
        detail="auto-allowed",
    )

    return report
