from __future__ import annotations

import pytest

from app.agent_framework.runtime import AgentEvent, RunEventService
from app.agent_framework.storage import PostgresAgentStore


@pytest.mark.asyncio
async def test_run_event_service_streams_tokens_and_persists_message_delta_on_flush():
    store = PostgresAgentStore()
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    run = store.create_run(session_id=session_id, agent_id="default", input="hi")
    run_id = str(run["id"])
    events = RunEventService(store=store, delta_flush_chars=999, delta_flush_seconds=999)

    await events.append_and_publish(
        session_id,
        run_id,
        AgentEvent(type="token", data={"content": "Hello"}),
    )

    stream = events.stream_run_events(run_id)
    event = await anext(stream)
    await stream.aclose()

    assert event.type == "token"
    assert event.data["content"] == "Hello"
    assert store.list_run_events(session_id) == []

    await events.flush_deltas(session_id, run_id, force=True)
    stored = store.list_run_events(session_id)
    assert len(stored) == 1
    assert stored[0]["type"] == "message_delta"
    assert stored[0]["payload"]["content"] == "Hello"
    assert stored[0]["payload"]["char_count"] == 5
    assert stored[0]["payload"]["agent_event"]["type"] == "message_delta"


@pytest.mark.asyncio
async def test_run_event_service_persists_reasoning_delta_on_flush():
    store = PostgresAgentStore()
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    run = store.create_run(session_id=session_id, agent_id="default", input="hi")
    run_id = str(run["id"])
    events = RunEventService(store=store, delta_flush_chars=999, delta_flush_seconds=999)

    await events.append_and_publish(
        session_id,
        run_id,
        AgentEvent(type="reasoning", data={"content": "thinking"}),
    )
    await events.flush_deltas(session_id, run_id, force=True)

    stored = store.list_run_events(session_id)
    assert len(stored) == 1
    assert stored[0]["type"] == "reasoning_delta"
    assert stored[0]["payload"]["content"] == "thinking"
    assert stored[0]["payload"]["agent_event"]["type"] == "reasoning_delta"


@pytest.mark.asyncio
async def test_run_event_service_batches_tokens_instead_of_persisting_each_token():
    store = PostgresAgentStore()
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    run = store.create_run(session_id=session_id, agent_id="default", input="hi")
    run_id = str(run["id"])
    events = RunEventService(store=store, delta_flush_chars=999, delta_flush_seconds=999)

    for token in ["Hel", "lo", " world"]:
        await events.append_and_publish(
            session_id,
            run_id,
            AgentEvent(type="token", data={"content": token}),
        )

    assert store.list_run_events(session_id) == []
    await events.flush_deltas(session_id, run_id, force=True)

    stored = store.list_run_events(session_id)
    assert len(stored) == 1
    assert stored[0]["type"] == "message_delta"
    assert stored[0]["payload"]["content"] == "Hello world"


@pytest.mark.asyncio
async def test_run_event_service_terminal_event_force_flushes_pending_delta_first():
    store = PostgresAgentStore()
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    run = store.create_run(session_id=session_id, agent_id="default", input="hi")
    run_id = str(run["id"])
    events = RunEventService(store=store, delta_flush_chars=999, delta_flush_seconds=999)

    await events.append_and_publish(
        session_id,
        run_id,
        AgentEvent(type="token", data={"content": "partial"}),
    )
    await events.append_and_publish(
        session_id,
        run_id,
        AgentEvent(type="cancelled", data={"status": "cancelled"}),
    )

    stored = store.list_run_events(session_id)
    assert [event["type"] for event in stored] == ["message_delta", "agent"]
    assert stored[0]["payload"]["content"] == "partial"
    assert stored[1]["payload"]["agent_event"]["type"] == "cancelled"
