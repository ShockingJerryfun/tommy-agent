from __future__ import annotations

import uuid

from app.agent_framework.runtime.event_bridge import EventBridge
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
        input="events",
        run_id=run_id,
        status="running",
    )
    return session_id, run_id


def test_event_bridge_persists_ordered_team_and_workflow_events() -> None:
    store = _store()
    session_id, parent_run_id = _new_session(store)
    bridge = EventBridge(store)

    bridge.emit_team_event(
        "team_run_started",
        session_id=session_id,
        parent_run_id=parent_run_id,
        team_run_id="team-run-1",
        team_id="team-1",
        status="running",
    )
    bridge.emit_team_event(
        "team_task_completed",
        session_id=session_id,
        parent_run_id=parent_run_id,
        team_run_id="team-run-1",
        team_id="team-1",
        team_task_id="task-1",
        status="completed",
    )
    bridge.emit_workflow_event(
        "workflow_worker_failed",
        session_id=session_id,
        parent_run_id=parent_run_id,
        workflow_run_id="workflow-1",
        phase_run_id="phase-run-1",
        worker_run_id="worker-1",
        status="failed",
    )

    events = bridge.list_for_parent_run(parent_run_id)

    assert [event["type"] for event in events] == [
        "team_run_started",
        "team_task_completed",
        "workflow_worker_failed",
    ]
    assert bridge.list_for_team_run("team-run-1")[1]["payload"]["team_task_id"] == "task-1"
    assert bridge.list_for_workflow_run("workflow-1")[0]["payload"]["worker_run_id"] == "worker-1"
