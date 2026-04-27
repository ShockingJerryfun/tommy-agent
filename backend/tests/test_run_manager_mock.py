from __future__ import annotations

import pytest

from app.agent_framework.runs import RunCreatePayload, RunManager
from app.agent_framework.store import SQLiteAgentStore, utc_now


class FakeChunk:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeCheckpointer:
    async def adelete_thread(self, session_id: str) -> None:
        return None


class MockStreamGraph:
    """Minimal stand-in for LangGraph: yields the same tuple shapes as astream."""

    def __init__(self, parts: list[tuple[str, object]]) -> None:
        self.checkpointer = _FakeCheckpointer()
        self._parts = parts

    async def astream(self, inputs, config=None, stream_mode=None):
        for part in self._parts:
            yield part


@pytest.mark.asyncio
async def test_run_manager_streams_tokens_and_completes(tmp_path):
    store = SQLiteAgentStore(tmp_path / "agent.sqlite")
    parts = [
        ("messages", (FakeChunk("Hello"), {"langgraph_node": "agent"})),
        ("messages", (FakeChunk(" world"), {"langgraph_node": "agent"})),
        ("updates", {"agent": {}}),
    ]
    graph = MockStreamGraph(parts)

    async def factory():
        return graph

    rm = RunManager(store=store, graph_factory=factory)
    session_id = store.create_session(agent_id="default")
    run = await rm.create_and_start_run(
        RunCreatePayload(session_id=session_id, message="Hi", agent_id="default"),
    )
    rid = str(run["id"])
    types: list[str] = []
    async for ev in rm.stream_run_events(rid):
        types.append(ev.type)

    assert "token" in types
    assert types[-1] == "done"

    finished = store.get_run(rid)
    assert finished is not None
    assert finished["status"] == "completed"

    messages = store.list_messages(session_id)
    assistant = [m for m in messages if m.role == "assistant"][-1]
    assert "Hello world" in assistant.content


@pytest.mark.asyncio
async def test_reconcile_orphan_inflight_marks_interrupted(tmp_path):
    store = SQLiteAgentStore(tmp_path / "agent.sqlite")
    session_id = store.create_session(agent_id="default")
    run = store.create_run(session_id=session_id, agent_id="default", input="orphan")
    store.update_run_status(str(run["id"]), status="running", started_at=utc_now())

    async def unused_factory():
        raise AssertionError("graph must not be built during orphan reconcile")

    rm = RunManager(store=store, graph_factory=unused_factory)
    finalized = await rm.reconcile_orphan_inflight_runs(session_id)
    assert finalized == [str(run["id"])]
    assert store.get_run(str(run["id"]))["status"] == "interrupted"
    assert store.get_active_run(session_id) is None
