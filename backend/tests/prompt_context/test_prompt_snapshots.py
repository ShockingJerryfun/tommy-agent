"""Postgres-side tests for the prompt_snapshots and memory_injections tables."""

from __future__ import annotations

from app.agent_framework.storage import PostgresAgentStore


def test_record_and_list_prompt_snapshot_with_injections() -> None:
    store = PostgresAgentStore()
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")

    memory = store.create_memory(
        agent_id="default",
        content="Tommy's owner is Fang Jin.",
        status="active",
    )

    snapshot = store.record_prompt_snapshot(
        session_id=session_id,
        agent_id="default",
        run_id="run-abc",
        model="deepseek-v4-pro",
        total_chars=1234,
        section_count=5,
        truncated_count=1,
        dropped_count=0,
        content_sha256="deadbeef",
        sections=[{"name": "runtime", "title": "Runtime"}],
        budget={"max_chars": 24000, "granted_chars": 1234},
        metadata={"node": "agent"},
        injections=[
            {
                "memory_id": memory["id"],
                "query": "who is the owner",
                "rank": 0,
                "score": None,
                "char_count": len(memory["content"]),
                "metadata": {"source": "search"},
            }
        ],
    )

    assert snapshot["id"].startswith("prompt-")
    fetched = store.get_prompt_snapshot(snapshot["id"])
    assert fetched is not None
    assert fetched["session_id"] == session_id
    assert fetched["run_id"] == "run-abc"
    assert fetched["content_sha256"] == "deadbeef"
    assert fetched["section_count"] == 5
    assert fetched["sections"] == [{"name": "runtime", "title": "Runtime"}]
    assert fetched["budget"]["max_chars"] == 24000

    listed = store.list_prompt_snapshots(session_id=session_id)
    assert any(item["id"] == snapshot["id"] for item in listed)

    injections = store.list_memory_injections_for_snapshot(snapshot["id"])
    assert len(injections) == 1
    assert injections[0]["memory_id"] == memory["id"]
    assert injections[0]["query"] == "who is the owner"
    assert injections[0]["rank"] == 0
    assert injections[0]["session_id"] == session_id

    by_session = store.list_memory_injections_for_session(session_id)
    assert len(by_session) == 1
    assert by_session[0]["memory_id"] == memory["id"]


def test_record_snapshot_without_injections_is_ok() -> None:
    store = PostgresAgentStore()
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")

    snapshot = store.record_prompt_snapshot(
        session_id=session_id,
        agent_id="default",
        run_id=None,
        model="",
        total_chars=10,
        section_count=1,
        truncated_count=0,
        dropped_count=0,
        content_sha256="abc123",
        sections=[],
        budget={},
        metadata=None,
        injections=None,
    )

    assert snapshot["id"]
    assert store.list_memory_injections_for_snapshot(snapshot["id"]) == []
