from __future__ import annotations

from app.agent_framework.store import SQLiteAgentStore


def test_update_message_content_and_metadata_status(tmp_path):
    store = SQLiteAgentStore(tmp_path / "agent.sqlite")
    session_id = store.create_session(agent_id="default")

    message = store.append_message(
        session_id,
        role="assistant",
        content="partial",
        metadata={"status": "running"},
    )

    updated = store.update_message(
        message.id,
        content="partial done",
        metadata={"status": "completed"},
    )
    assert updated is not None
    assert updated.content == "partial done"
    assert updated.metadata["status"] == "completed"

    cancelled = store.update_message(
        message.id,
        metadata={"status": "cancelled"},
    )
    assert cancelled is not None
    assert cancelled.content == "partial done"
    assert cancelled.metadata["status"] == "cancelled"

    messages = store.list_messages(session_id)
    assert messages[-1].content == "partial done"
    assert messages[-1].metadata["status"] == "cancelled"
