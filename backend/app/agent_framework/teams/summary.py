"""Bounded Agent Team summaries for parent context."""

from __future__ import annotations

from typing import Any


def team_summary_markdown(
    *,
    team: dict[str, Any],
    tasks: list[dict[str, Any]],
    max_chars: int = 1800,
) -> str:
    lines = [
        "## Team Results",
        f"- Goal: {team['goal']}",
        f"- Status: {team['status']}",
    ]
    for task in tasks:
        lines.append(f"- {task['title']} [{task['status']}]")
        if task.get("result_subagent_id"):
            lines.append(f"  - Result: {task['result_subagent_id']}")
        if task.get("result_summary"):
            lines.append(f"  - Summary: {str(task['result_summary']).strip()}")
    return _truncate("\n".join(lines), max_chars)


def team_summary_section(
    store: Any,
    *,
    parent_session_id: str,
    limit: int = 5,
    max_chars: int = 1800,
) -> str:
    if not hasattr(store, "agent_teams"):
        return ""
    teams = store.agent_teams.list_for_session(parent_session_id, limit=limit)
    blocks: list[str] = []
    remaining = max_chars
    for team in teams:
        tasks = store.agent_team_tasks.list_for_team(team["id"])
        block = team_summary_markdown(team=team, tasks=tasks, max_chars=remaining)
        if block:
            blocks.append(block)
            remaining = max(0, max_chars - len("\n\n".join(blocks)))
        if remaining <= 0:
            break
    return _truncate("\n\n".join(blocks), max_chars)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
