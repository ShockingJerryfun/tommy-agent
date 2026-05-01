from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.agent_framework.runtime import RunCreatePayload, RunManager
from app.agent_framework.server import app as api_module
from app.agent_framework.storage import PostgresAgentStore


def test_message_repo_delete_after_keeps_positions_through_target():
    store = PostgresAgentStore()
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    for index in range(5):
        store.append_message(
            session_id,
            role="user" if index % 2 == 0 else "assistant",
            content=f"message {index}",
        )

    removed = store.delete_messages_after(session_id, 2)

    assert removed == 2
    assert {message.position for message in store.list_messages(session_id)} == {0, 1, 2}


def test_patch_message_edits_user_and_rejects_assistant():
    store = api_module._agent_store
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    user = store.append_message(session_id, role="user", content="before")
    assistant = store.append_message(session_id, role="assistant", content="reply")

    client = TestClient(api_module.app)
    response = client.patch(f"/api/messages/{user.id}", json={"content": "after"})

    assert response.status_code == 200
    assert response.json()["content"] == "after"
    assert store.get_message(user.id).content == "after"

    rejected = client.patch(f"/api/messages/{assistant.id}", json={"content": "nope"})
    assert rejected.status_code == 422


def test_rerun_message_edits_deletes_downstream_and_starts_skip_user_run(monkeypatch):
    store = api_module._agent_store
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    target = store.append_message(session_id, role="user", content="old")
    downstream = store.append_message(session_id, role="assistant", content="old reply")
    captured: dict[str, RunCreatePayload] = {}

    async def fake_create_and_start_run(payload: RunCreatePayload) -> dict[str, str]:
        captured["payload"] = payload
        return {"id": "run-rerun", "status": "queued"}

    monkeypatch.setattr(api_module._run_manager, "create_and_start_run", fake_create_and_start_run)

    client = TestClient(api_module.app)
    response = client.post(
        f"/api/messages/{target.id}/rerun",
        json={"content": "new", "idempotency_key": "rerun-key"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == "run-rerun"
    assert store.get_message(downstream.id) is None
    messages = store.list_messages(session_id)
    assert [message.id for message in messages] == [target.id]
    assert messages[0].content == "new"
    payload = captured["payload"]
    assert payload.message == "new"
    assert payload.skip_user_persist is True
    assert payload.idempotency_key == "rerun-key"
    assert payload.metadata["rerun"] is True
    assert payload.metadata["target_user_message_id"] == target.id


def test_regenerate_message_deletes_after_parent_user_and_starts_run(monkeypatch):
    store = api_module._agent_store
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    first_user = store.append_message(session_id, role="user", content="first")
    first_assistant = store.append_message(session_id, role="assistant", content="first reply")
    parent_user = store.append_message(session_id, role="user", content="parent")
    target = store.append_message(session_id, role="assistant", content="regenerate me")
    captured: dict[str, RunCreatePayload] = {}

    async def fake_create_and_start_run(payload: RunCreatePayload) -> dict[str, str]:
        captured["payload"] = payload
        return {"id": "run-regen", "status": "queued"}

    monkeypatch.setattr(api_module._run_manager, "create_and_start_run", fake_create_and_start_run)

    client = TestClient(api_module.app)
    response = client.post(
        f"/api/messages/{target.id}/regenerate",
        json={"idempotency_key": "regen-key"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == "run-regen"
    assert [message.id for message in store.list_messages(session_id)] == [
        first_user.id,
        first_assistant.id,
        parent_user.id,
    ]
    payload = captured["payload"]
    assert payload.message == "parent"
    assert payload.skip_user_persist is True
    assert payload.idempotency_key == "regen-key"
    assert payload.metadata["regenerate"] is True
    assert payload.metadata["target_user_message_id"] == parent_user.id


@pytest.mark.asyncio
async def test_run_manager_idempotency_key_returns_existing_run(monkeypatch):
    store = PostgresAgentStore()
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    manager = RunManager(store=store)

    async def noop_execute_run(run_id: str, payload: RunCreatePayload) -> None:
        return None

    monkeypatch.setattr(manager, "execute_run", noop_execute_run)
    payload = RunCreatePayload(
        session_id=session_id,
        message="hello",
        agent_id="default",
        idempotency_key="same-key",
    )

    first = await manager.create_and_start_run(payload)
    await asyncio.sleep(0)
    second = await manager.create_and_start_run(payload)

    assert first["id"] == second["id"]
    matching_runs = [
        run for run in store.list_runs(session_id, limit=10) if run["idempotency_key"] == "same-key"
    ]
    assert len(matching_runs) == 1
