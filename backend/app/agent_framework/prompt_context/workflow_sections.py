"""Bounded prompt sections for workflow worker context."""

from __future__ import annotations

from typing import Any


def workflow_phase_context_section(
    store: Any,
    metadata: dict[str, Any],
    *,
    max_chars: int = 1600,
) -> str:
    workflow_run_id = str(metadata.get("workflow_run_id") or "")
    if not workflow_run_id:
        return ""
    current_phase = str(metadata.get("workflow_phase_id") or "")
    phases = store.workflow_phase_runs.list_for_run(workflow_run_id)
    lines = [
        f"workflow_run_id: {workflow_run_id}",
        f"current_phase: {current_phase}",
        "Phases:",
    ]
    for phase in phases:
        lines.append(f"- {phase['phase_id']}: {phase['status']}")
    return _truncate("\n".join(lines), max_chars)


def child_constraints_section(metadata: dict[str, Any]) -> str:
    if not metadata.get("is_child") and not metadata.get("depth"):
        return ""
    return "\n".join(
        [
            "Child constraints:",
            "- Do not spawn teams or workflows.",
            "- Return bounded summaries and artifact references.",
            "- Do not include full transcripts in parent context.",
        ]
    )


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
