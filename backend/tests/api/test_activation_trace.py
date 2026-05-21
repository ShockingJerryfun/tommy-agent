from __future__ import annotations

from fastapi.testclient import TestClient

from app.agent_framework.server import app as api_module


def test_run_activation_trace_endpoint_returns_trace_context() -> None:
    store = api_module._agent_store
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    run = store.create_run(
        session_id=session_id,
        agent_id="default",
        input="inspect localhost",
        run_id="run-activation-api",
    )
    snapshot = store.record_prompt_snapshot(
        session_id=session_id,
        agent_id="default",
        run_id=str(run["id"]),
        model="test-model",
        total_chars=10,
        section_count=1,
        truncated_count=0,
        dropped_count=0,
        content_sha256="api-trace",
        sections=[],
        budget={},
        metadata={
            "skill_activation": {
                "selected": [
                    {
                        "skill_id": "skill-api",
                        "name": "browser",
                        "required_tools": ["browser.open"],
                    }
                ]
            }
        },
    )
    store.upsert_tool_call(
        session_id,
        run_id=str(run["id"]),
        tool_call_id="call-api",
        name="browser.open",
        status="done",
    )
    store.record_skill_activation_trace(
        session_id=session_id,
        run_id=str(run["id"]),
        snapshot_id=str(snapshot["id"]),
        skill_id="skill-api",
        skill_name="browser",
        required_tools=["browser.open"],
        matched_tools=["browser.open"],
        credited=True,
        terminal_status="completed",
        terminal_reason="completed",
        selected={"skill_id": "skill-api", "name": "browser"},
    )

    client = TestClient(api_module.app)
    response = client.get("/api/runs/run-activation-api/activation-trace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["id"] == "run-activation-api"
    assert payload["snapshots"][0]["metadata"]["skill_activation"]["selected"][0][
        "skill_id"
    ] == "skill-api"
    assert payload["trace_rows"][0]["credited"] is True
    assert payload["trace_rows"][0]["matched_tools"] == ["browser.open"]
    assert payload["tool_calls"][0]["name"] == "browser.open"


def test_run_activation_trace_endpoint_404s_for_missing_run() -> None:
    store = api_module._agent_store
    store.reset_for_tests()
    client = TestClient(api_module.app)

    response = client.get("/api/runs/missing-run/activation-trace")

    assert response.status_code == 404
