"""Task board facade for Agent Teams."""

from __future__ import annotations

from typing import Any


class TeamTaskBoard:
    def __init__(self, store: Any) -> None:
        self.store = store

    def list_tasks(self, team_id: str) -> list[dict[str, Any]]:
        return self.store.agent_team_tasks.list_for_team(team_id)

    def bounded_section(self, team_id: str, *, max_chars: int = 1600) -> str:
        lines = ["Task Board"]
        for task in self.list_tasks(team_id):
            deps = ", ".join(task.get("dependencies") or []) or "none"
            lines.append(
                f"- {task['id']}: {task['status']} | {task['title']} | deps: {deps}"
            )
        text = "\n".join(lines)
        if len(text) <= max_chars:
            return text
        return text[: max(0, max_chars - 3)].rstrip() + "..."
