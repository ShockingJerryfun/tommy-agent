from __future__ import annotations

import uuid
from typing import Any

from app.agent_framework.graph import routing
from app.agent_framework.storage import PostgresAgentStore


def _store() -> PostgresAgentStore:
    store = PostgresAgentStore()
    store.reset_for_tests()
    return store


def _session(store: PostgresAgentStore, *, prefix: str) -> tuple[str, str]:
    session_id = f"{prefix}-sess-{uuid.uuid4().hex[:8]}"
    run_id = f"{prefix}-run-{uuid.uuid4().hex[:8]}"
    store.create_session(session_id=session_id, agent_id="default", title=prefix)
    return session_id, run_id


def _state(
    *,
    session_id: str,
    run_id: str,
    parent_session_id: str = "",
    parent_run_id: str = "",
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "metadata": {
            "run_id": run_id,
            "parent_session_id": parent_session_id,
            "parent_run_id": parent_run_id,
        },
    }


def test_child_run_does_not_treat_parent_approval_interruption_as_stop(
    monkeypatch: Any,
) -> None:
    store = _store()
    parent_session_id, parent_run_id = _session(store, prefix="parent")
    child_session_id, child_run_id = _session(store, prefix="child")
    store.create_run(
        session_id=parent_session_id,
        agent_id="default",
        input="needs approval",
        run_id=parent_run_id,
        status="interrupted",
    )
    store.start_run(parent_session_id, run_id=parent_run_id)
    store.finish_run(parent_session_id, run_id=parent_run_id, status="stopped")
    store.create_run(
        session_id=child_session_id,
        agent_id="default",
        input="child",
        run_id=child_run_id,
        status="running",
    )
    monkeypatch.setattr(routing, "get_agent_store", lambda: store)

    stopped = routing.run_stop_requested(
        _state(
            session_id=child_session_id,
            run_id=child_run_id,
            parent_session_id=parent_session_id,
            parent_run_id=parent_run_id,
        )
    )

    assert stopped is False


def test_child_run_honors_explicit_parent_stop(monkeypatch: Any) -> None:
    store = _store()
    parent_session_id, parent_run_id = _session(store, prefix="parent")
    child_session_id, child_run_id = _session(store, prefix="child")
    store.create_run(
        session_id=parent_session_id,
        agent_id="default",
        input="running",
        run_id=parent_run_id,
        status="running",
    )
    store.start_run(parent_session_id, run_id=parent_run_id)
    store.request_run_stop(parent_session_id, run_id=parent_run_id)
    store.create_run(
        session_id=child_session_id,
        agent_id="default",
        input="child",
        run_id=child_run_id,
        status="running",
    )
    monkeypatch.setattr(routing, "get_agent_store", lambda: store)

    stopped = routing.run_stop_requested(
        _state(
            session_id=child_session_id,
            run_id=child_run_id,
            parent_session_id=parent_session_id,
            parent_run_id=parent_run_id,
        )
    )

    assert stopped is True
