from __future__ import annotations

import pytest

from app.agent_framework.events import AgentEvent
from app.agent_framework.runtime import RunEventService
from app.agent_framework.store import PostgresAgentStore


@pytest.mark.asyncio
async def test_run_event_service_replays_transient_tokens_without_persisting_them():
    store = PostgresAgentStore()
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    run = store.create_run(session_id=session_id, agent_id="default", input="hi")
    run_id = str(run["id"])
    events = RunEventService(store=store)

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
