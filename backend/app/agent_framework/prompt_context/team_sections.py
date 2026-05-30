"""Bounded prompt sections for team worker context."""

from __future__ import annotations

from typing import Any


def active_team_role_section(metadata: dict[str, Any]) -> str:
    team_id = str(metadata.get("team_id") or "")
    team_task_id = str(metadata.get("team_task_id") or "")
    if not team_id and not team_task_id:
        return ""
    role = str(metadata.get("subagent_role") or metadata.get("role_id") or "")
    return "\n".join(
        line
        for line in [
            f"team_id: {team_id}" if team_id else "",
            f"team_run_id: {metadata.get('team_run_id')}" if metadata.get("team_run_id") else "",
            f"team_task_id: {team_task_id}" if team_task_id else "",
            f"role: {role}" if role else "",
        ]
        if line
    )


def team_task_board_section(store: Any, metadata: dict[str, Any], *, max_chars: int = 1600) -> str:
    team_id = str(metadata.get("team_id") or "")
    if not team_id:
        return ""
    tasks = store.agent_team_tasks.list_for_team(team_id)
    lines = ["Task Board"]
    for task in tasks:
        lines.append(f"- {task['id']}: {task['status']} | {task['title']}")
    return _truncate("\n".join(lines), max_chars)


def team_mailbox_section(store: Any, metadata: dict[str, Any], *, max_chars: int = 1200) -> str:
    team_id = str(metadata.get("team_id") or "")
    if not team_id:
        return ""
    messages = store.agent_team_messages.list_for_team(team_id, limit=10)
    lines = ["Mailbox"]
    for message in messages:
        sender = message.get("from_member_id") or "team"
        lines.append(f"- {sender}: {message.get('content', '')}")
    return _truncate("\n".join(lines), max_chars)


def parent_multi_agent_summary_section(
    store: Any,
    *,
    parent_session_id: str,
    max_chars: int = 1800,
) -> str:
    if not parent_session_id:
        return ""
    lines: list[str] = []
    if not hasattr(store, "agent_teams") or not hasattr(store, "subagent_runs"):
        return ""
    teams = store.agent_teams.list_for_session(parent_session_id, limit=5)
    for team in teams:
        lines.append(f"- Team {team['id']}: {team['status']} | {team['goal']}")
    subagents = store.subagent_runs.list_for_session(parent_session_id, limit=8)
    for row in subagents:
        lines.append(f"- Child {row['id']}: {row['status']} | {row['role_id']}")
    return _truncate("\n".join(lines), max_chars)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
