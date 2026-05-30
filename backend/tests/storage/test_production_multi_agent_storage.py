from __future__ import annotations

import uuid

from app.agent_framework.storage import PostgresAgentStore


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
        input="runtime",
        run_id=run_id,
        status="running",
    )
    return session_id, run_id


def test_subagent_run_lineage_is_queryable_without_metadata() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)
    child_session_id = store.create_session(agent_id="default", title="child")

    row = store.subagent_runs.create(
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        child_session_id=child_session_id,
        child_run_id="child-run-1",
        role="reviewer",
        task="review",
        status="running",
        metadata={"debug": "kept"},
        role_id="reviewer",
        agent_definition_id="reviewer",
        team_id="team-1",
        team_run_id="team-run-1",
        team_task_id="team-task-1",
        workflow_run_id="workflow-1",
        phase_run_id="phase-run-1",
        workflow_phase_id="phase-1",
        approval_id="approval-1",
    )
    store.subagent_runs.update(
        row["id"],
        status="failed",
        error_type="RuntimeError",
        error_message="boom",
        finished=True,
    )

    hydrated = store.subagent_runs.get(row["id"])

    assert hydrated is not None
    assert hydrated["role_id"] == "reviewer"
    assert hydrated["agent_definition_id"] == "reviewer"
    assert hydrated["team_id"] == "team-1"
    assert hydrated["team_run_id"] == "team-run-1"
    assert hydrated["team_task_id"] == "team-task-1"
    assert hydrated["workflow_run_id"] == "workflow-1"
    assert hydrated["phase_run_id"] == "phase-run-1"
    assert hydrated["workflow_phase_id"] == "phase-1"
    assert hydrated["approval_id"] == "approval-1"
    assert hydrated["error_type"] == "RuntimeError"
    assert hydrated["error_message"] == "boom"
    assert hydrated["metadata"] == {"debug": "kept"}


def test_team_runs_and_artifacts_are_first_class_records() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)
    team = store.agent_teams.create(
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        goal="Audit runtime",
    )
    team_run = store.agent_team_runs.create(
        team_id=team["id"],
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        approval_id="approval-1",
        goal="Audit runtime",
        metadata={"source": "test"},
    )
    artifact = store.artifacts.create(
        owner_run_id=parent_run_id,
        owner_type="team",
        subagent_run_id="sub-1",
        team_run_id=team_run["id"],
        kind="summary",
        uri="artifact://summary/1",
        path="",
        sha256="abc",
        size_bytes=123,
        summary="bounded output",
    )

    assert team_run["status"] == "queued"
    assert store.agent_team_runs.get(team_run["id"])["team_id"] == team["id"]
    assert store.artifacts.list_for_owner(parent_run_id)[0]["id"] == artifact["id"]
    assert store.artifacts.list_for_subagent("sub-1")[0]["summary"] == "bounded output"


def test_cleanup_repository_hooks_are_deterministic() -> None:
    store = _store()

    assert store.subagent_runs.list_old_completed_child_runs(limit=10) == []
    assert store.subagent_runs.truncate_large_child_outputs(max_chars=100) == 0
    assert store.artifacts.list_orphan_artifacts(limit=10) == []
    assert store.artifacts.delete_orphan_artifacts(limit=10) == 0
    assert store.agent_team_runs.mark_running_background_jobs_interrupted() == 0
    assert store.workflow_runs.mark_running_background_jobs_interrupted() == 0
