"""Production team runtime with lead planning and persisted task board state."""

from __future__ import annotations

import asyncio
from typing import Any

from ..runtime.background_tasks import CancellationToken
from ..runtime.event_bridge import EventBridge
from ..storage import PostgresAgentStore
from ..workers import WorkerPool, WorkerResult, WorkerRunner, WorkerTask
from ..workers.context import merge_child_parent_metadata
from .coordinator import team_status_from_task_statuses
from .mailbox import TeamMailbox
from .planner import MinimalTeamPlanner, PlannedTeamTask, TeamPlanner
from .summary import team_summary_markdown
from .task_board import TeamTaskBoard


class TeamRuntime:
    def __init__(
        self,
        store: PostgresAgentStore,
        *,
        planner: TeamPlanner | None = None,
        worker_runner: WorkerRunner | None = None,
        max_tasks: int = 12,
        max_concurrency: int = 4,
        event_bridge: EventBridge | None = None,
    ) -> None:
        self.store = store
        self._planner = planner or MinimalTeamPlanner(max_tasks=max_tasks)
        self._worker_runner = worker_runner
        self._max_tasks = max_tasks
        self._max_concurrency = max_concurrency
        self._events = event_bridge or EventBridge(store)
        self._board = TeamTaskBoard(store)
        self._mailbox = TeamMailbox(store)

    async def run(
        self,
        team_run_id: str,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> dict[str, Any]:
        token = cancellation_token or CancellationToken()
        team_run = self.store.agent_team_runs.get(team_run_id)
        if team_run is None:
            raise KeyError(f"unknown team run: {team_run_id}")
        team = self.store.agent_teams.get(team_run["team_id"])
        if team is None:
            raise KeyError(f"unknown team: {team_run['team_id']}")

        self.store.agent_team_runs.update(team_run_id, status="running")
        self._events.emit_team_event(
            "team_run_started",
            session_id=team_run["parent_session_id"],
            parent_run_id=team_run["parent_run_id"],
            team_run_id=team_run_id,
            team_id=team["id"],
            status="running",
        )
        try:
            self._ensure_tasks(team)
            await self._run_task_waves(team, team_run, token)
            token.raise_if_cancelled()
        except asyncio.CancelledError:
            self.store.agent_team_runs.update(team_run_id, status="stopped", finished=True)
            self._events.emit_team_event(
                "background_run_cancelled",
                session_id=team_run["parent_session_id"],
                parent_run_id=team_run["parent_run_id"],
                team_run_id=team_run_id,
                team_id=team["id"],
                status="cancelled",
            )
            raise

        latest_tasks = self.store.agent_team_tasks.list_for_team(team["id"])
        status = team_status_from_task_statuses([task["status"] for task in latest_tasks])
        summary = team_summary_markdown(
            team={**team, "status": status},
            tasks=latest_tasks,
            max_chars=1800,
        )
        if status == "completed":
            summary_result = await self._run_lead_synthesis(team, team_run, latest_tasks)
            if summary_result.status == "completed" and summary_result.final_response.strip():
                summary = _truncate(summary_result.final_response, 1800)
            else:
                status = "failed"
                summary = _truncate(
                    f"{summary}\n\nLead synthesis failed: {summary_result.final_response}",
                    1800,
                )
            self._mailbox.post(
                team_id=team["id"],
                from_member_id=team.get("lead_member_id") or "",
                kind="summary",
                content=summary,
            )
            event_type = "team_run_completed"
        else:
            event_type = "team_run_failed"
        self._events.emit_team_event(
            event_type,
            session_id=team_run["parent_session_id"],
            parent_run_id=team_run["parent_run_id"],
            team_run_id=team_run_id,
            team_id=team["id"],
            status=status,
        )
        return self.store.agent_team_runs.update(
            team_run_id,
            status=status,
            summary=summary,
            finished=True,
        ) or {}

    async def _run_lead_synthesis(
        self,
        team: dict[str, Any],
        team_run: dict[str, Any],
        tasks: list[dict[str, Any]],
    ) -> WorkerResult:
        lead_member = self._lead_member(team)
        self._events.emit_team_event(
            "team_synthesis_started",
            session_id=team_run["parent_session_id"],
            parent_run_id=team_run["parent_run_id"],
            team_run_id=team_run["id"],
            team_id=team["id"],
            status="running",
        )
        results = await WorkerPool(
            store=self.store,
            runner=self._worker_runner,
            max_concurrency=1,
        ).run([self._lead_synthesis_task(team, team_run, tasks, lead_member)])
        result = results[0]
        self._events.emit_team_event(
            "team_synthesis_completed"
            if result.status == "completed"
            else "team_synthesis_failed",
            session_id=team_run["parent_session_id"],
            parent_run_id=team_run["parent_run_id"],
            team_run_id=team_run["id"],
            team_id=team["id"],
            status=result.status,
            payload={
                "subagent_run_id": result.subagent_id,
                "child_session_id": result.child_session_id,
            },
        )
        return result

    def _ensure_tasks(self, team: dict[str, Any]) -> None:
        existing = self.store.agent_team_tasks.list_for_team(team["id"])
        if existing:
            return
        members = self.store.agent_team_members.list_for_team(team["id"])
        planned = self._planner.plan(goal=team["goal"], members=members)[: self._max_tasks]
        for planned_task in planned:
            self._create_planned_task(team["id"], planned_task)

    def _create_planned_task(self, team_id: str, planned_task: PlannedTeamTask) -> None:
        member = self._select_member(team_id, planned_task.assigned_role or None)
        self.store.agent_team_tasks.create(
            team_id=team_id,
            title=planned_task.title,
            description=planned_task.description,
            assigned_member_id=member["id"],
            dependencies=planned_task.dependencies,
            priority=planned_task.priority,
        )

    async def _run_task_waves(
        self,
        team: dict[str, Any],
        team_run: dict[str, Any],
        token: CancellationToken,
    ) -> None:
        while True:
            token.raise_if_cancelled()
            tasks = self.store.agent_team_tasks.list_for_team(team["id"])
            queued = [task for task in tasks if task["status"] == "queued"]
            if not queued:
                return
            ready = [task for task in queued if self._dependencies_completed(tasks, task)]
            if not ready:
                for task in queued:
                    self.store.agent_team_tasks.update(
                        task["id"],
                        status="failed",
                        error_type="DependencyError",
                        error_message="No queued tasks could be scheduled.",
                        finished=True,
                    )
                return
            for task in ready:
                self.store.agent_team_tasks.update(
                    task["id"],
                    status="running",
                    team_run_id=team_run["id"],
                )
                self._events.emit_team_event(
                    "team_task_started",
                    session_id=team_run["parent_session_id"],
                    parent_run_id=team_run["parent_run_id"],
                    team_run_id=team_run["id"],
                    team_id=team["id"],
                    team_task_id=task["id"],
                    status="running",
                )

            results = await WorkerPool(
                store=self.store,
                runner=self._worker_runner,
                max_concurrency=self._max_concurrency,
            ).run([self._worker_task(team, team_run, task) for task in ready])
            self._persist_results(team, team_run, ready, results)

    def _persist_results(
        self,
        team: dict[str, Any],
        team_run: dict[str, Any],
        tasks: list[dict[str, Any]],
        results: list[WorkerResult],
    ) -> None:
        by_task_id = {result.task_id: result for result in results}
        for task in tasks:
            result = by_task_id[task["id"]]
            final_status = result.status if result.status in {"completed", "stopped"} else "failed"
            error_type = str(result.metadata.get("error_type") or "") if result.metadata else ""
            self.store.agent_team_tasks.update(
                task["id"],
                status=final_status,
                result_subagent_id=result.subagent_id,
                result_summary=_truncate(result.final_response, 1200),
                error_type=error_type,
                error_message="" if final_status == "completed" else result.final_response,
                metadata_patch={
                    "child_session_id": result.child_session_id,
                    "role_id": result.role_id,
                    "team_run_id": team_run["id"],
                },
                finished=True,
            )
            self._mailbox.post(
                team_id=team["id"],
                from_member_id=task["assigned_member_id"],
                task_id=task["id"],
                kind="result",
                content=_truncate(result.final_response, 800),
            )
            self._events.emit_team_event(
                "team_task_completed" if final_status == "completed" else "team_task_failed",
                session_id=team_run["parent_session_id"],
                parent_run_id=team_run["parent_run_id"],
                team_run_id=team_run["id"],
                team_id=team["id"],
                team_task_id=task["id"],
                status=final_status,
            )

    def _worker_task(
        self,
        team: dict[str, Any],
        team_run: dict[str, Any],
        task: dict[str, Any],
    ) -> WorkerTask:
        member = self.store.agent_team_members.get(task["assigned_member_id"])
        if member is None:
            raise ValueError(f"task {task['id']} has no assigned team member")
        team_metadata = team.get("metadata") if isinstance(team.get("metadata"), dict) else {}
        task_metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
        metadata = merge_child_parent_metadata(
            team_metadata,
            {
                **task_metadata,
                "team_id": team["id"],
                "team_run_id": team_run["id"],
                "team_task_id": task["id"],
                "approval_id": team_run.get("approval_id") or "",
            },
        )
        prompt = "\n\n".join(
            [
                f"Assigned task: {task['title']}\n{task['description']}",
                self._board.bounded_section(team["id"]),
                self._mailbox.bounded_section(team["id"]),
                f"Role constraints: {member['role']} / {member['agent_definition_id']}",
            ]
        )
        return WorkerTask(
            id=task["id"],
            role_id=member["agent_definition_id"],
            task=prompt,
            reason=f"Team goal: {team['goal']}",
            parent_session_id=team_run["parent_session_id"],
            parent_run_id=team_run["parent_run_id"],
            agent_id=str(metadata.get("agent_id") or "default"),
            metadata=metadata,
            approval_id=str(metadata.get("approval_id") or ""),
        )

    def _lead_synthesis_task(
        self,
        team: dict[str, Any],
        team_run: dict[str, Any],
        tasks: list[dict[str, Any]],
        lead_member: dict[str, Any],
    ) -> WorkerTask:
        metadata = merge_child_parent_metadata(
            team.get("metadata") if isinstance(team.get("metadata"), dict) else {},
            {
                "team_id": team["id"],
                "team_run_id": team_run["id"],
                "approval_id": team_run.get("approval_id") or "",
            },
        )
        task_lines = [
            f"- {task['title']} [{task['status']}]: {task.get('result_summary') or ''}"
            for task in tasks
        ]
        prompt = "\n\n".join(
            [
                "Synthesize the final team result for the parent user.",
                f"Team goal: {team['goal']}",
                "Task results:\n" + "\n".join(task_lines),
                self._board.bounded_section(team["id"]),
                self._mailbox.bounded_section(team["id"]),
                "Return a concise final answer with decisions, evidence, and remaining risks.",
            ]
        )
        return WorkerTask(
            id=f"{team_run['id']}:synthesis",
            role_id=lead_member["agent_definition_id"],
            task=prompt,
            reason=f"Team lead synthesis: {team['goal']}",
            parent_session_id=team_run["parent_session_id"],
            parent_run_id=team_run["parent_run_id"],
            agent_id=str(metadata.get("agent_id") or "default"),
            metadata=metadata,
            approval_id=str(metadata.get("approval_id") or ""),
        )

    def _lead_member(self, team: dict[str, Any]) -> dict[str, Any]:
        lead_member_id = str(team.get("lead_member_id") or "")
        if lead_member_id:
            lead = self.store.agent_team_members.get(lead_member_id)
            if lead is not None:
                return lead
        members = self.store.agent_team_members.list_for_team(team["id"])
        for member in members:
            if member["role"] == "lead":
                return member
        return members[0]

    def _select_member(self, team_id: str, assigned_role: str | None) -> dict[str, Any]:
        members = self.store.agent_team_members.list_for_team(team_id)
        if not members:
            raise ValueError("team has no members")
        if assigned_role:
            for member in members:
                if (
                    member["role"] == assigned_role
                    or member["agent_definition_id"] == assigned_role
                ):
                    return member
        return members[0]

    @staticmethod
    def _dependencies_completed(tasks: list[dict[str, Any]], task: dict[str, Any]) -> bool:
        by_id = {row["id"]: row for row in tasks}
        return all(by_id.get(dep, {}).get("status") == "completed" for dep in task["dependencies"])


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
