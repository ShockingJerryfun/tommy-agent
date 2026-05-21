from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.agent_framework.runtime import RunCreatePayload, RunManager
from app.agent_framework.storage import PostgresAgentStore, utc_now


class FakeChunk:
    def __init__(
        self,
        content: str,
        *,
        additional_kwargs: dict[str, object] | None = None,
        response_metadata: dict[str, object] | None = None,
        usage_metadata: dict[str, object] | None = None,
    ) -> None:
        self.content = content
        self.additional_kwargs = additional_kwargs or {}
        self.response_metadata = response_metadata or {}
        self.usage_metadata = usage_metadata or {}


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


class BlockingStreamGraph:
    def __init__(self, release: asyncio.Event) -> None:
        self.checkpointer = _FakeCheckpointer()
        self._release = release

    async def astream(self, inputs, config=None, stream_mode=None):
        yield ("messages", (FakeChunk("streamed"), {"langgraph_node": "agent"}))
        await self._release.wait()


@pytest.mark.asyncio
async def test_run_manager_streams_tokens_and_completes():
    store = PostgresAgentStore()
    store.reset_for_tests()
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

    stored_events = store.list_run_events(session_id)
    stored_agent_events = [
        (event.get("payload") or {}).get("agent_event", {}) for event in stored_events
    ]
    message_deltas = [event for event in stored_events if event["type"] == "message_delta"]
    assert all(event.get("type") != "token" for event in stored_agent_events)
    assert len(message_deltas) == 1
    assert message_deltas[0]["payload"]["content"] == "Hello world"
    model_events = [event for event in stored_events if event["type"].startswith("model_")]
    assert [event["type"] for event in model_events] == ["model_start", "model_end"]
    metrics = store.get_run_metrics(session_id=session_id, run_id=rid)
    assert metrics is not None
    assert metrics["terminal_reason"] == "completed"
    assert metrics["status"] == "completed"
    assert metrics["duration_ms"] >= 0
    assert metrics["tool_count"] == 0
    assert metrics["error_count"] == 0
    assert metrics["cancelled"] is False
    assert metrics["interrupted"] is False


@pytest.mark.asyncio
async def test_run_manager_records_failure_metrics_and_model_error():
    store = PostgresAgentStore()
    store.reset_for_tests()

    class FailingGraph:
        checkpointer = _FakeCheckpointer()

        async def astream(self, inputs, config=None, stream_mode=None):
            if False:
                yield None
            raise RuntimeError("model exploded")

    async def factory():
        return FailingGraph()

    rm = RunManager(store=store, graph_factory=factory)
    session_id = store.create_session(agent_id="default")
    run = await rm.create_and_start_run(
        RunCreatePayload(session_id=session_id, message="Hi", agent_id="default"),
    )
    rid = str(run["id"])
    async for ev in rm.stream_run_events(rid):
        if ev.type == "done":
            break

    stored_events = store.list_run_events(session_id)
    assert [event["type"] for event in stored_events if event["type"].startswith("model_")] == [
        "model_start",
        "model_error",
    ]
    metrics = store.get_run_metrics(session_id=session_id, run_id=rid)
    assert metrics is not None
    assert metrics["terminal_reason"] == "error"
    assert metrics["status"] == "error"
    assert metrics["error_count"] == 1


@pytest.mark.asyncio
async def test_run_manager_records_token_usage_when_available():
    store = PostgresAgentStore()
    store.reset_for_tests()
    parts = [
        (
            "messages",
            (
                FakeChunk(
                    "Hello",
                    usage_metadata={
                        "input_tokens": 3,
                        "output_tokens": 5,
                        "total_tokens": 8,
                    },
                    response_metadata={"model_name": "test-model", "finish_reason": "stop"},
                ),
                {"langgraph_node": "agent"},
            ),
        )
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
    async for ev in rm.stream_run_events(rid):
        if ev.type == "done":
            break

    metrics = store.get_run_metrics(session_id=session_id, run_id=rid)
    assert metrics is not None
    assert metrics["model"] == "test-model"
    assert metrics["prompt_tokens"] == 3
    assert metrics["completion_tokens"] == 5
    assert metrics["total_tokens"] == 8
    assert metrics["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_run_manager_persists_reasoning_delta_and_assistant_parts():
    store = PostgresAgentStore()
    store.reset_for_tests()
    parts = [
        (
            "messages",
            (
                FakeChunk("", additional_kwargs={"reasoning_content": "think"}),
                {"langgraph_node": "agent"},
            ),
        ),
        ("messages", (FakeChunk("answer"), {"langgraph_node": "agent"})),
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
    async for ev in rm.stream_run_events(rid):
        if ev.type == "done":
            break

    stored_events = store.list_run_events(session_id)
    reasoning_deltas = [event for event in stored_events if event["type"] == "reasoning_delta"]
    message_deltas = [event for event in stored_events if event["type"] == "message_delta"]
    assert len(reasoning_deltas) == 1
    assert len(message_deltas) == 1
    assert reasoning_deltas[0]["payload"]["content"] == "think"
    assert message_deltas[0]["payload"]["content"] == "answer"

    assistant = [m for m in store.list_messages(session_id) if m.role == "assistant"][-1]
    assert assistant.content == "answer"
    assert assistant.metadata["parts"][0]["type"] == "reasoning"
    assert assistant.metadata["parts"][0]["content"] == "think"
    assert assistant.metadata["parts"][1]["type"] == "text"
    assert assistant.metadata["parts"][1]["content"] == "answer"


@pytest.mark.asyncio
async def test_run_manager_cancel_force_flushes_pending_delta_and_assistant_message():
    store = PostgresAgentStore()
    store.reset_for_tests()
    parts = [
        ("messages", (FakeChunk("partial"), {"langgraph_node": "agent"})),
        ("messages", (FakeChunk(" ignored"), {"langgraph_node": "agent"})),
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

    observed: list[str] = []
    async for ev in rm.stream_run_events(rid):
        observed.append(ev.type)
        if ev.type == "token":
            await rm.cancel_run(rid)
        if ev.type == "cancelled":
            break

    assert observed[-1] == "cancelled"
    assert store.get_run(rid)["status"] == "cancelled"

    stored_events = store.list_run_events(session_id)
    message_deltas = [event for event in stored_events if event["type"] == "message_delta"]
    assert len(message_deltas) == 1
    assert message_deltas[0]["payload"]["content"] == "partial"

    assistant = [m for m in store.list_messages(session_id) if m.role == "assistant"][-1]
    assert assistant.content == "partial"
    assert assistant.metadata["status"] == "cancelled"


@pytest.mark.asyncio
async def test_run_manager_stream_close_force_flushes_pending_delta():
    store = PostgresAgentStore()
    store.reset_for_tests()
    release = asyncio.Event()
    graph = BlockingStreamGraph(release)

    async def factory():
        return graph

    rm = RunManager(store=store, graph_factory=factory)
    session_id = store.create_session(agent_id="default")
    run = await rm.create_and_start_run(
        RunCreatePayload(session_id=session_id, message="Hi", agent_id="default"),
    )
    rid = str(run["id"])

    stream = rm.stream_run_events(rid)
    event = await anext(stream)
    if event.type == "model_start":
        event = await anext(stream)
    assert event.type == "token"
    await stream.aclose()

    try:
        stored_events = store.list_run_events(session_id)
        message_deltas = [event for event in stored_events if event["type"] == "message_delta"]
        assert len(message_deltas) == 1
        assert message_deltas[0]["payload"]["content"] == "streamed"
    finally:
        release.set()
        await rm.cancel_run(rid)


@pytest.mark.asyncio
async def test_run_manager_halts_when_tool_waits_for_approval():
    store = PostgresAgentStore()
    store.reset_for_tests()
    parts = [
        (
            "custom",
            {
                "type": "tool_start",
                "tool": "run_shell_command",
                "tool_call_id": "call-1",
                "args": {"command": "pwd"},
            },
        ),
        (
            "custom",
            {
                "type": "tool_end",
                "tool": "run_shell_command",
                "tool_call_id": "call-1",
                "status": "pending_approval",
                "content": "queued for approval",
            },
        ),
    ]
    graph = MockStreamGraph(parts)

    async def factory():
        return graph

    rm = RunManager(store=store, graph_factory=factory)
    session_id = store.create_session(agent_id="default")
    run = await rm.create_and_start_run(
        RunCreatePayload(session_id=session_id, message="Run pwd", agent_id="default"),
    )
    rid = str(run["id"])
    observed: list[str] = []
    async for ev in rm.stream_run_events(rid):
        observed.append(ev.type)
        if ev.type == "tool_end":
            break
    task = rm._tasks.get(rid)
    if task is not None:
        await task

    assert observed[-2:] == ["tool_start", "tool_end"]
    assert store.get_run(rid)["status"] == "interrupted"
    assistant = [m for m in store.list_messages(session_id) if m.role == "assistant"][-1]
    assert (assistant.metadata or {}).get("status") == "waiting_approval"


@pytest.mark.asyncio
async def test_run_manager_records_skill_activation_trace_and_credits_once():
    store = PostgresAgentStore()
    store.reset_for_tests()
    skill = store.skill_catalog.register_skill(
        agent_id="default",
        name="browser",
        relative_path="browser/SKILL.md",
        signature="browser automation",
        description="Browser automation.",
        tool_chain=["browser.open"],
        status="active",
    )

    class TraceGraph:
        checkpointer = _FakeCheckpointer()

        async def astream(self, inputs, config=None, stream_mode=None):
            run_id = inputs["metadata"]["run_id"]
            session_id = inputs["session_id"]
            store.record_prompt_snapshot(
                session_id=session_id,
                agent_id="default",
                run_id=run_id,
                model="test-model",
                total_chars=10,
                section_count=1,
                truncated_count=0,
                dropped_count=0,
                content_sha256="trace",
                sections=[],
                budget={},
                metadata={
                    "skill_activation": {
                        "selected": [
                            {
                                "skill_id": skill["id"],
                                "name": "browser",
                                "relative_path": "browser/SKILL.md",
                                "required_tools": ["browser.open"],
                            }
                        ]
                    }
                },
            )
            store.record_prompt_snapshot(
                session_id=session_id,
                agent_id="default",
                run_id=run_id,
                model="test-model",
                total_chars=10,
                section_count=1,
                truncated_count=0,
                dropped_count=0,
                content_sha256="trace-second",
                sections=[],
                budget={},
                metadata={
                    "skill_activation": {
                        "selected": [
                            {
                                "skill_id": skill["id"],
                                "name": "browser",
                                "relative_path": "browser/SKILL.md",
                                "required_tools": ["browser.open"],
                            }
                        ]
                    }
                },
            )
            yield (
                "custom",
                {
                    "type": "tool_start",
                    "tool": "browser.open",
                    "tool_call_id": "call-browser",
                    "args": {"url": "http://localhost"},
                },
            )
            yield (
                "custom",
                {
                    "type": "tool_end",
                    "tool": "browser.open",
                    "tool_call_id": "call-browser",
                    "status": "ok",
                    "content": "opened",
                },
            )
            yield ("messages", (FakeChunk("done"), {"langgraph_node": "agent"}))

    async def factory():
        return TraceGraph()

    rm = RunManager(store=store, graph_factory=factory)
    session_id = store.create_session(agent_id="default")
    run = await rm.create_and_start_run(
        RunCreatePayload(session_id=session_id, message="inspect localhost", agent_id="default"),
    )
    rid = str(run["id"])
    async for ev in rm.stream_run_events(rid):
        if ev.type == "done":
            break

    traces = store.list_skill_activation_traces_for_run(rid)
    assert len(traces) == 2
    assert [trace["matched_tools"] for trace in traces] == [["browser.open"], ["browser.open"]]
    assert sum(1 for trace in traces if trace["credited"]) == 1
    updated = store.skill_catalog.get(skill["id"])
    assert updated is not None
    assert updated["success_count"] == 1
    assert updated["invocation_count"] == 1

    metrics = store.get_run_metrics(session_id=session_id, run_id=rid)
    rm._record_skill_activation_feedback(
        SimpleNamespace(session_id=session_id, run_id=rid),
        status="completed",
        terminal_reason="completed",
        metrics_row=metrics,
    )
    assert len(store.list_skill_activation_traces_for_run(rid)) == 2
    assert store.skill_catalog.get(skill["id"])["invocation_count"] == 1


@pytest.mark.asyncio
async def test_reconcile_orphan_inflight_marks_interrupted():
    store = PostgresAgentStore()
    store.reset_for_tests()
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


def test_run_manager_uses_checkpoint_history_for_normal_turns():
    store = PostgresAgentStore()
    rm = RunManager(store=store)
    payload = RunCreatePayload(
        session_id="session",
        message="next",
        agent_id="default",
        history=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    )

    assert rm._build_history_messages(payload) == []
