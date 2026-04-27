from __future__ import annotations

import pytest

from app.agent_framework.runtime import GraphRuntime


class _FakeCheckpointer:
    def __init__(self) -> None:
        self.deleted_threads: list[str] = []

    async def adelete_thread(self, session_id: str) -> None:
        self.deleted_threads.append(session_id)


class _FakeGraph:
    def __init__(self) -> None:
        self.checkpointer = _FakeCheckpointer()
        self.calls: list[dict[str, object]] = []

    async def astream(self, inputs, config=None, stream_mode=None):
        self.calls.append(
            {
                "inputs": inputs,
                "config": config,
                "stream_mode": stream_mode,
            }
        )
        yield ("updates", {"agent": {}})


@pytest.mark.asyncio
async def test_graph_runtime_streams_with_thread_config():
    graph = _FakeGraph()

    async def factory():
        return graph

    runtime = GraphRuntime(graph_factory=factory)
    parts = [part async for part in runtime.stream("session-1", {"messages": []})]

    assert parts == [("updates", {"agent": {}})]
    assert graph.calls[0]["config"] == {"configurable": {"thread_id": "session-1"}}
    assert graph.calls[0]["stream_mode"] == ["messages", "updates", "custom"]


@pytest.mark.asyncio
async def test_graph_runtime_resets_checkpoint_thread():
    graph = _FakeGraph()

    async def factory():
        return graph

    runtime = GraphRuntime(graph_factory=factory)
    await runtime.reset_thread("session-1")

    assert graph.checkpointer.deleted_threads == ["session-1"]
