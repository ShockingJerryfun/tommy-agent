from __future__ import annotations

from fastapi.testclient import TestClient

from app.agent_framework.server import app as api_module


def test_search_returns_unique_message_with_highlighted_snippet():
    store = api_module._agent_store
    store.reset_for_tests()
    first_session = store.create_session(agent_id="default", title="First")
    second_session = store.create_session(agent_id="default", title="Second")
    target = None

    for index in range(3):
        content = "the platypus marker lives here" if index == 1 else f"ordinary first {index}"
        message = store.append_message(first_session, role="user", content=content)
        if index == 1:
            target = message
    for index in range(3):
        store.append_message(second_session, role="assistant", content=f"ordinary second {index}")

    assert target is not None
    client = TestClient(api_module.app)
    response = client.get("/api/search", params={"q": "platypus"})

    assert response.status_code == 200
    results = response.json()["results"]
    assert [item["message_id"] for item in results] == [target.id]
    assert results[0]["snippet"]
    assert "<mark>" in results[0]["snippet"]


def test_search_rejects_empty_query():
    client = TestClient(api_module.app)
    response = client.get("/api/search", params={"q": ""})

    assert response.status_code == 422
