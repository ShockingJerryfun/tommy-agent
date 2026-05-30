from __future__ import annotations

import asyncio
import uuid

import pytest

from app.agent_framework.runtime.background_tasks import CancellationToken
from app.agent_framework.storage import PostgresAgentStore
from app.agent_framework.teams.planner import PlannedTeamTask, StaticTeamPlanner
from app.agent_framework.teams.runtime import TeamRuntime
from app.agent_framework.workers import WorkerResult, WorkerTask


def _store() -> PostgresAgentStore:
    store = PostgresAgentStore()
    store.reset_for_tests()
    return store


def _new_session(store: PostgresAgentStore) -> tuple[str, str]:
    session_id = f"sess-{uuid.uuid4().hex[:10]}"
    store.create_session(session_id=session_id, agent_id="default", title="t")
    run_id = f"run-{uuid.uuid4().hex[:10]}"
    store.create_run(
        session_id=session_id,
        agent_id="default",
        input="team",
        run_id=run_id,
        status="running",
    )
    return session_id, run_id


@pytest.mark.asyncio
async def test_team_runtime_plans_when_no_tasks_and_synthesizes_summary() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)
    team = store.agent_teams.create(
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        goal="Ship runtime",
    )
    lead = store.agent_team_members.create(
        team_id=team["id"],
        role="lead",
        agent_definition_id="architect",
    )
    store.agent_teams.update(team["id"], lead_member_id=lead["id"])
    team_run = store.agent_team_runs.create(
        team_id=team["id"],
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        approval_id="approval-1",
        goal="Ship runtime",
    )
    calls: list[str] = []

    async def runner(task: WorkerTask) -> WorkerResult:
        assert "Task Board" in task.task
        assert "Mailbox" in task.task
        calls.append(task.id)
        return WorkerResult(
            task_id=task.id,
            subagent_id=f"sub-{task.id}",
            child_session_id=f"child-{task.id}",
            role_id=task.role_id,
            status="completed",
            final_response=f"done {task.id}",
        )

    planner = StaticTeamPlanner(
        [
            PlannedTeamTask(
                title="Review storage",
                description="Check storage",
                assigned_role="lead",
            )
        ]
    )
    result = await TeamRuntime(store, planner=planner, worker_runner=runner).run(
        team_run["id"],
        cancellation_token=CancellationToken(),
    )

    assert result["status"] == "completed"
    assert result["summary"]
    assert store.agent_team_runs.get(team_run["id"])["summary"] == result["summary"]
    assert store.agent_team_tasks.list_for_team(team["id"])[0]["status"] == "completed"
    assert calls[-1] == f"{team_run['id']}:synthesis"


@pytest.mark.asyncio
async def test_team_runtime_respects_dependencies_and_parallel_ready_tasks() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)
    team = store.agent_teams.create(
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        goal="Order tasks",
    )
    member = store.agent_team_members.create(
        team_id=team["id"],
        role="reviewer",
        agent_definition_id="reviewer",
    )
    first = store.agent_team_tasks.create(
        team_id=team["id"],
        title="First",
        description="First",
        assigned_member_id=member["id"],
    )
    store.agent_team_tasks.create(
        team_id=team["id"],
        title="Second A",
        description="Second A",
        assigned_member_id=member["id"],
        dependencies=[first["id"]],
    )
    store.agent_team_tasks.create(
        team_id=team["id"],
        title="Second B",
        description="Second B",
        assigned_member_id=member["id"],
        dependencies=[first["id"]],
    )
    team_run = store.agent_team_runs.create(
        team_id=team["id"],
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        approval_id="approval-1",
        goal="Order tasks",
    )
    waves: list[list[str]] = []
    active: set[str] = set()

    async def runner(task: WorkerTask) -> WorkerResult:
        active.add(task.id)
        waves.append(sorted(active))
        await asyncio.sleep(0.01)
        active.remove(task.id)
        return WorkerResult(
            task_id=task.id,
            subagent_id=f"sub-{task.id}",
            child_session_id=f"child-{task.id}",
            role_id=task.role_id,
            status="completed",
            final_response="done",
        )

    await TeamRuntime(store, worker_runner=runner).run(
        team_run["id"],
        cancellation_token=CancellationToken(),
    )

    assert waves[0] == [first["id"]]
    assert any(len(wave) == 2 for wave in waves)


@pytest.mark.asyncio
async def test_team_runtime_cancellation_stops_future_scheduling() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)
    team = store.agent_teams.create(
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        goal="Cancel",
    )
    member = store.agent_team_members.create(
        team_id=team["id"],
        role="reviewer",
        agent_definition_id="reviewer",
    )
    first = store.agent_team_tasks.create(
        team_id=team["id"],
        title="First",
        description="First",
        assigned_member_id=member["id"],
    )
    store.agent_team_tasks.create(
        team_id=team["id"],
        title="Second",
        description="Second",
        assigned_member_id=member["id"],
        dependencies=[first["id"]],
    )
    team_run = store.agent_team_runs.create(
        team_id=team["id"],
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        approval_id="approval-1",
        goal="Cancel",
    )
    token = CancellationToken()

    async def runner(task: WorkerTask) -> WorkerResult:
        token.cancel("test")
        return WorkerResult(
            task_id=task.id,
            subagent_id=f"sub-{task.id}",
            child_session_id=f"child-{task.id}",
            role_id=task.role_id,
            status="completed",
            final_response="done",
        )

    with pytest.raises(asyncio.CancelledError):
        await TeamRuntime(store, worker_runner=runner).run(
            team_run["id"],
            cancellation_token=token,
        )

    tasks = store.agent_team_tasks.list_for_team(team["id"])
    assert [task["status"] for task in tasks] == ["completed", "queued"]
