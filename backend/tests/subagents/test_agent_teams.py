"""Agent Teams MVP tests."""

from __future__ import annotations

import uuid

import pytest

from app.agent_framework.storage import PostgresAgentStore
from app.agent_framework.teams import TeamService, team_summary_section
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
async def test_create_team_with_members_and_tasks() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)
    service = TeamService(store)

    team = service.create_team(
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        goal="Review the runtime",
        members=[
            {"role": "lead", "agent_definition_id": "architect"},
            {"role": "reviewer", "agent_definition_id": "reviewer"},
        ],
    )
    task = service.create_task(
        team["id"],
        title="Review storage",
        description="Find persistence regressions",
        assigned_role="reviewer",
    )

    assert team["status"] == "queued"
    assert len(store.agent_team_members.list_for_team(team["id"])) == 2
    assert task["status"] == "queued"
    assert store.agent_team_tasks.list_for_team(team["id"])[0]["title"] == "Review storage"


@pytest.mark.asyncio
async def test_run_team_with_fake_worker_persists_results_and_summary() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)

    async def runner(task: WorkerTask) -> WorkerResult:
        assert task.child_context is not None
        assert task.child_context.team_id
        assert task.child_context.team_task_id == task.id
        return WorkerResult(
            task_id=task.id,
            subagent_id=f"sub-{task.id}",
            child_session_id=f"child-{task.id}",
            role_id=task.role_id,
            status="completed",
            final_response=f"{task.role_id} completed {task.task}",
            score=0.75,
        )

    service = TeamService(store, worker_runner=runner)
    team = service.create_team(
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        goal="Audit modules",
        members=[
            {"role": "explorer", "agent_definition_id": "explorer"},
            {"role": "reviewer", "agent_definition_id": "reviewer"},
        ],
    )
    service.create_task(team["id"], title="Inspect graph", description="Inspect graph module")
    service.create_task(
        team["id"],
        title="Review subagents",
        description="Review subagent module",
        assigned_role="reviewer",
    )

    result = await service.run_team(team["id"], max_concurrency=2)

    assert result["status"] == "completed"
    tasks = store.agent_team_tasks.list_for_team(team["id"])
    assert [task["status"] for task in tasks] == ["completed", "completed"]
    assert all(task["result_subagent_id"].startswith("sub-") for task in tasks)
    summary = service.summarize_team(team["id"])
    assert "Team Results" in summary
    assert "Inspect graph" in summary
    assert "Review subagents" in summary
    assert "completed" in team_summary_section(store, parent_session_id=parent_session_id)


@pytest.mark.asyncio
async def test_failed_team_task_does_not_corrupt_whole_team() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)

    async def runner(task: WorkerTask) -> WorkerResult:
        if "bad" in task.task:
            raise RuntimeError("bad task")
        return WorkerResult(
            task_id=task.id,
            subagent_id=f"sub-{task.id}",
            child_session_id=f"child-{task.id}",
            role_id=task.role_id,
            status="completed",
            final_response="ok",
        )

    service = TeamService(store, worker_runner=runner)
    team = service.create_team(
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        goal="Mixed result",
        members=[{"role": "reviewer", "agent_definition_id": "reviewer"}],
    )
    service.create_task(team["id"], title="Good", description="good")
    service.create_task(team["id"], title="Bad", description="bad")

    result = await service.run_team(team["id"])

    assert result["status"] == "failed"
    statuses = [task["status"] for task in store.agent_team_tasks.list_for_team(team["id"])]
    assert statuses == ["completed", "failed"]
    summary = service.summarize_team(team["id"], max_chars=400)
    assert "worker error: bad task" in summary


def test_team_summary_is_bounded_and_excludes_full_transcripts() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)
    service = TeamService(store)
    team = service.create_team(
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        goal="Bound summary",
        members=[{"role": "reviewer", "agent_definition_id": "reviewer"}],
    )
    task = service.create_task(team["id"], title="Huge", description="Huge response")
    store.agent_team_tasks.update(
        task["id"],
        status="completed",
        result_subagent_id="sub-large",
        result_summary="x" * 5000,
        finished=True,
    )

    summary = service.summarize_team(team["id"], max_chars=500)

    assert len(summary) <= 500
    assert "x" * 1000 not in summary
