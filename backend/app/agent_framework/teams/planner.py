"""Schema-validated team planning interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class PlannedTeamTask:
    title: str
    description: str
    assigned_role: str = ""
    dependencies: list[str] = field(default_factory=list)
    priority: int = 0


class TeamPlanner(Protocol):
    def plan(self, *, goal: str, members: list[dict[str, object]]) -> list[PlannedTeamTask]:
        """Return bounded tasks for a team goal."""


class StaticTeamPlanner:
    def __init__(self, tasks: list[PlannedTeamTask]) -> None:
        self._tasks = list(tasks)

    def plan(self, *, goal: str, members: list[dict[str, object]]) -> list[PlannedTeamTask]:
        return list(self._tasks)


class MinimalTeamPlanner:
    def __init__(self, *, max_tasks: int = 6) -> None:
        self._max_tasks = max(1, max_tasks)

    def plan(self, *, goal: str, members: list[dict[str, object]]) -> list[PlannedTeamTask]:
        non_lead = [
            member
            for member in members
            if str(member.get("role") or "") != "lead"
        ]
        candidates = non_lead or members
        tasks = []
        for member in candidates[: self._max_tasks]:
            role = str(member.get("role") or member.get("agent_definition_id") or "")
            tasks.append(
                PlannedTeamTask(
                    title=f"{role or 'agent'} contribution",
                    description=f"Complete the portion of this goal assigned to {role}: {goal}",
                    assigned_role=role,
                )
            )
        return tasks
