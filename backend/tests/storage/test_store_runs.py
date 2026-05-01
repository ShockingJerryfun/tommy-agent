from __future__ import annotations

from app.agent_framework.storage import PostgresAgentStore


def test_create_update_cancel_and_list_runs():
    store = PostgresAgentStore()
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")

    run = store.create_run(session_id=session_id, agent_id="default", input="hello")
    assert run["status"] == "queued"
    assert run["metadata"] == {}
    assert run["cancel_requested"] is False

    running = store.update_run_status(
        run["id"],
        status="running",
        assistant_message_id="msg-1",
        metadata={"source": "test"},
        started_at="2026-01-01T00:00:00+00:00",
    )
    assert running is not None
    assert running["status"] == "running"
    assert running["assistant_message_id"] == "msg-1"
    assert running["metadata"] == {"source": "test"}
    assert store.get_active_run(session_id)["id"] == run["id"]

    cancelled = store.update_run_status(
        run["id"],
        status="cancelled",
        finished_at="2026-01-01T00:00:05+00:00",
    )
    assert cancelled is not None
    assert cancelled["status"] == "cancelled"
    assert store.get_active_run(session_id) is None

    error_run = store.create_run(session_id=session_id, agent_id="default", input="boom")
    errored = store.update_run_status(error_run["id"], status="error", error="failed")
    assert errored is not None
    assert errored["error"] == "failed"

    latest = store.get_latest_run(session_id)
    assert latest is not None
    assert latest["id"] == error_run["id"]
    assert [item["id"] for item in store.list_runs(session_id, limit=2)] == [
        error_run["id"],
        run["id"],
    ]


def test_run_cancel_request_and_run_event_sequence_filtering():
    store = PostgresAgentStore()
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    run = store.create_run(session_id=session_id, agent_id="default", input="hello")
    other = store.create_run(session_id=session_id, agent_id="default", input="other")

    assert store.is_run_cancel_requested(run["id"]) is False
    requested = store.request_run_cancel(run["id"])
    assert requested is not None
    assert requested["cancel_requested"] is True
    assert store.is_run_cancel_requested(run["id"]) is True

    first = store.append_run_event(
        session_id,
        run_id=run["id"],
        type="agent",
        label="first",
        payload={"n": 1},
    )
    second = store.append_run_event(
        session_id,
        run_id=run["id"],
        type="agent",
        label="second",
        payload={"n": 2},
    )
    store.append_run_event(
        session_id,
        run_id=other["id"],
        type="agent",
        label="other",
        payload={"n": 3},
    )

    assert [item["id"] for item in store.list_run_events_after(run["id"])] == [
        first["id"],
        second["id"],
    ]
    assert [
        item["id"]
        for item in store.list_run_events_after(
            run["id"],
            after_sequence=first["sequence"],
        )
    ] == [second["id"]]


def test_finalize_run_as_interrupted_closes_run_and_inserts_terminal_event():
    store = PostgresAgentStore()
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    run = store.create_run(session_id=session_id, agent_id="default", input="x")
    store.update_run_status(
        str(run["id"]),
        status="running",
        started_at="2026-01-01T00:00:00+00:00",
    )
    assistant = store.append_message(
        session_id,
        role="assistant",
        content="partial",
        metadata={"source": "run", "run_id": str(run["id"]), "status": "running", "parts": []},
    )
    store.update_run_status(str(run["id"]), assistant_message_id=assistant.id)

    updated = store.finalize_run_as_interrupted(str(run["id"]), reason="unit-test")
    assert updated is not None
    assert updated["status"] == "interrupted"
    assert store.get_active_run(session_id) is None

    events = store.list_run_events_after(str(run["id"]))
    assert events and events[-1]["payload"].get("agent_event", {}).get("type") == "interrupted"

    msg = store.list_messages(session_id)
    ast = next(m for m in msg if m.id == assistant.id)
    assert ast.metadata.get("status") == "interrupted"
