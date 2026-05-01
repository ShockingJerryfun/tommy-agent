from __future__ import annotations

from fastapi.testclient import TestClient

from app.agent_framework.server import app as api_module


def test_session_detail_includes_assistant_run_summary() -> None:
    store = api_module._agent_store
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    run_id = "run-summary-test"
    store.append_message(session_id, role="user", content="hello")
    assistant = store.append_message(
        session_id,
        role="assistant",
        content="hi",
        metadata={"run_id": run_id},
    )
    store.run_metrics.upsert(
        session_id=session_id,
        run_id=run_id,
        agent_id="default",
        started_at="2026-04-28T00:00:00+00:00",
        finished_at="2026-04-28T00:00:01+00:00",
        duration_ms=1234.5,
        model="deepseek-v4-pro",
        prompt_tokens=123,
        completion_tokens=456,
        total_tokens=579,
        finish_reason="stop",
    )

    client = TestClient(api_module.app)
    response = client.get(f"/api/sessions/{session_id}")

    assert response.status_code == 200
    messages = response.json()["messages"]
    assistant_payload = next(message for message in messages if message["id"] == assistant.id)
    assert assistant_payload["run_summary"] == {
        "run_id": run_id,
        "model": "deepseek-v4-pro",
        "prompt_tokens": 123,
        "completion_tokens": 456,
        "total_tokens": 579,
        "latency_ms": 1234.5,
        "finish_reason": "stop",
        "started_at": "2026-04-28T00:00:00+00:00",
        "finished_at": "2026-04-28T00:00:01+00:00",
    }
