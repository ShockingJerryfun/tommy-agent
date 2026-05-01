from __future__ import annotations

from app.agent_framework.runtime import AssistantMessageWriter
from app.agent_framework.storage import PostgresAgentStore


def test_assistant_message_writer_batches_token_persistence():
    store = PostgresAgentStore()
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    message = store.append_message(
        session_id,
        role="assistant",
        content="",
        metadata={"status": "running"},
    )
    writer = AssistantMessageWriter(
        store=store,
        message=message,
        run_id="run-1",
        min_tokens_between_flushes=2,
        max_seconds_between_flushes=999,
    )

    writer.append_text("Hel")
    writer.flush()

    stored = store.list_messages(session_id)[-1]
    assert stored.content == ""

    writer.append_text("lo")
    writer.flush()

    stored = store.list_messages(session_id)[-1]
    assert stored.content == "Hello"
    assert stored.metadata["run_id"] == "run-1"
    assert stored.metadata["parts"][0]["content"] == "Hello"


def test_assistant_message_writer_force_flushes_tool_parts():
    store = PostgresAgentStore()
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    message = store.append_message(session_id, role="assistant", content="")
    writer = AssistantMessageWriter(store=store, message=message, run_id="run-1")

    writer.upsert_tool(
        {
            "id": "tool-1",
            "name": "shell",
            "status": "running",
            "summary": "ls",
        }
    )
    writer.flush(force=True)

    stored = store.list_messages(session_id)[-1]
    assert stored.metadata["parts"][0]["tool"]["id"] == "tool-1"
    assert stored.metadata["parts"][0]["tool"]["status"] == "running"
