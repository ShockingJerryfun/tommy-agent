"""Agent Teams service built on WorkerPool."""

from __future__ import annotations

from typing import Any

from ..storage import PostgresAgentStore
from ..workers import WorkerPool, WorkerRunner, WorkerTask
from .coordinator import team_status_from_task_statuses
from .summary import team_summary_markdown


class TeamService:
    def __init__(
        self,
        store: PostgresAgentStore,
        *,
        worker_runner: WorkerRunner | None = None,
    ) -> None:
        self.store = store
        self._worker_runner = worker_runner

    def create_team(
        self,
        *,
        parent_session_id: str,
        parent_run_id: str,
        goal: str,
        members: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not members:
            raise ValueError("team requires at least one member")
        team = self.store.agent_teams.create(
            parent_session_id=parent_session_id,
            parent_run_id=parent_run_id,
            goal=goal,
            metadata=metadata,
        )
        created_members = []
        for member in members:
            role = str(member.get("role") or member.get("agent_definition_id") or "").strip()
            definition_id = str(member.get("agent_definition_id") or role).strip()
            if not role or not definition_id:
                raise ValueError("team member role and agent_definition_id are required")
            metadata = member.get("metadata") if isinstance(member.get("metadata"), dict) else None
            created_members.append(
                self.store.agent_team_members.create(
                    team_id=team["id"],
                    role=role,
                    agent_definition_id=definition_id,
                    metadata=metadata,
                )
            )
        return self.store.agent_teams.update(
            team["id"],
            lead_member_id=created_members[0]["id"],
        ) or team

    def create_task(
        self,
        team_id: str,
        *,
        title: str,
        description: str,
        assigned_role: str | None = None,
        dependencies: list[str] | None = None,
        priority: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        member = self._select_member(team_id, assigned_role)
        return self.store.agent_team_tasks.create(
            team_id=team_id,
            title=title,
            description=description,
            assigned_member_id=member["id"],
            dependencies=dependencies,
            priority=priority,
            metadata=metadata,
        )

    async def run_team(self, team_id: str, *, max_concurrency: int = 4) -> dict[str, Any]:
        team = self.store.agent_teams.get(team_id)
        if team is None:
            raise KeyError(f"unknown team: {team_id}")
        self.store.agent_teams.update(team_id, status="running")
        tasks = [
            task for task in self.store.agent_team_tasks.list_for_team(team_id)
            if task["status"] == "queued" and self._dependencies_completed(team_id, task)
        ]
        for task in tasks:
            self.store.agent_team_tasks.update(task["id"], status="running")

        worker_tasks = [self._worker_task(team, task) for task in tasks]
        pool = WorkerPool(
            store=self.store,
            runner=self._worker_runner,
            max_concurrency=max_concurrency,
        )
        results = await pool.run(worker_tasks)
        by_task_id = {result.task_id: result for result in results}
        for task in tasks:
            result = by_task_id[task["id"]]
            final_status = result.status if result.status in {"completed", "stopped"} else "failed"
            self.store.agent_team_tasks.update(
                task["id"],
                status=final_status,
                result_subagent_id=result.subagent_id,
                result_summary=_truncate(result.final_response, 1200),
                metadata_patch={
                    "child_session_id": result.child_session_id,
                    "score": result.score,
                    "role_id": result.role_id,
                },
                finished=True,
            )

        latest_tasks = self.store.agent_team_tasks.list_for_team(team_id)
        status = team_status_from_task_statuses([task["status"] for task in latest_tasks])
        summary = self.summarize_team(team_id)
        return self.store.agent_teams.update(
            team_id,
            status=status,
            metadata_patch={"summary": summary},
            finished=status in {"completed", "failed", "stopped"},
        ) or {}

    def summarize_team(self, team_id: str, *, max_chars: int = 1800) -> str:
        team = self.store.agent_teams.get(team_id)
        if team is None:
            raise KeyError(f"unknown team: {team_id}")
        tasks = self.store.agent_team_tasks.list_for_team(team_id)
        return team_summary_markdown(team=team, tasks=tasks, max_chars=max_chars)

    def _select_member(self, team_id: str, assigned_role: str | None) -> dict[str, Any]:
        members = self.store.agent_team_members.list_for_team(team_id)
        if not members:
            raise ValueError("team has no members")
        if assigned_role:
            for member in members:
                matches_role = (
                    member["role"] == assigned_role
                    or member["agent_definition_id"] == assigned_role
                )
                if matches_role:
                    return member
            raise ValueError(f"team has no member for role: {assigned_role}")
        for member in members:
            if member["role"] != "lead":
                return member
        return members[0]

    def _dependencies_completed(self, team_id: str, task: dict[str, Any]) -> bool:
        dependencies = set(task.get("dependencies") or [])
        if not dependencies:
            return True
        tasks = {row["id"]: row for row in self.store.agent_team_tasks.list_for_team(team_id)}
        return all(tasks.get(dep, {}).get("status") == "completed" for dep in dependencies)

    def _worker_task(self, team: dict[str, Any], task: dict[str, Any]) -> WorkerTask:
        member = self.store.agent_team_members.get(task["assigned_member_id"])
        if member is None:
            raise ValueError(f"task {task['id']} has no assigned team member")
        return WorkerTask(
            id=task["id"],
            role_id=member["agent_definition_id"],
            task=f"{task['title']}\n\n{task['description']}",
            reason=f"Team goal: {team['goal']}",
            parent_session_id=team["parent_session_id"],
            parent_run_id=team["parent_run_id"],
            agent_id="default",
            metadata={"team_id": team["id"], "team_task_id": task["id"]},
        )


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
