"""Task board facade for Agent Teams."""

from __future__ import annotations

from typing import Any


class TeamTaskBoard:
    def __init__(self, store: Any) -> None:
        self.store = store

    def list_tasks(self, team_id: str) -> list[dict[str, Any]]:
        return self.store.agent_team_tasks.list_for_team(team_id)
