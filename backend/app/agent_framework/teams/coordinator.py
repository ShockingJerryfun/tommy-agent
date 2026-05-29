"""Team coordination helpers for the MVP lead-controlled runtime."""

from __future__ import annotations


def team_status_from_task_statuses(statuses: list[str]) -> str:
    if not statuses:
        return "completed"
    if any(status == "stopped" for status in statuses):
        return "stopped"
    if any(status == "failed" for status in statuses):
        return "failed"
    if all(status == "completed" for status in statuses):
        return "completed"
    return "running"
