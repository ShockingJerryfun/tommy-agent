from __future__ import annotations

from fastapi.testclient import TestClient

from app.agent_framework.server import app as api_module
from app.agent_framework.storage import PostgresAgentStore


def test_update_session_metadata_modifies_fields_independently():
    store = PostgresAgentStore()
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default", title="Original")

    renamed = store.update_session_metadata(session_id, title="Renamed")
    pinned = store.update_session_metadata(session_id, pinned=True)
    archived = store.update_session_metadata(session_id, archived=True)

    assert renamed is not None
    assert renamed["title"] == "Renamed"
    assert renamed["pinned"] is False
    assert pinned is not None
    assert pinned["title"] == "Renamed"
    assert pinned["pinned"] is True
    assert pinned["archived"] is False
    assert archived is not None
    assert archived["pinned"] is True
    assert archived["archived"] is True


def test_patch_session_rejects_empty_body():
    store = api_module._agent_store
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")

    client = TestClient(api_module.app)
    response = client.patch(f"/api/sessions/{session_id}", json={})

    assert response.status_code == 422


def test_share_token_round_trip():
    store = PostgresAgentStore()
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")

    store.set_share_token(session_id, "token-123")
    shared = store.get_session_by_share_token("token-123")

    assert shared is not None
    assert shared["id"] == session_id


def test_share_endpoint_returns_readonly_payload_and_revoke_404s():
    store = api_module._agent_store
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default", title="Shared")
    user = store.append_message(session_id, role="user", content="hello share")
    assistant = store.append_message(session_id, role="assistant", content="shared reply")

    client = TestClient(api_module.app)
    response = client.post(f"/api/sessions/{session_id}/share")

    assert response.status_code == 200
    token = response.json()["token"]
    shared = client.get(f"/share/{token}")
    assert shared.status_code == 200
    payload = shared.json()
    assert payload["session"]["id"] == session_id
    assert set(payload["session"]) == {"id", "title", "created_at", "updated_at"}
    assert payload["messages"] == [
        {
            "id": user.id,
            "role": "user",
            "content": "hello share",
            "created_at": user.created_at,
        },
        {
            "id": assistant.id,
            "role": "assistant",
            "content": "shared reply",
            "created_at": assistant.created_at,
        },
    ]

    revoked = client.delete(f"/api/sessions/{session_id}/share")
    assert revoked.status_code == 200
    assert revoked.json() == {"status": "revoked"}
    assert client.get(f"/share/{token}").status_code == 404


def test_export_markdown_returns_download_with_content():
    store = api_module._agent_store
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    store.append_message(session_id, role="user", content="Export title")
    store.append_message(session_id, role="assistant", content="assistant export content")

    client = TestClient(api_module.app)
    response = client.get(f"/api/sessions/{session_id}/export?format=md")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert 'filename="export-title.md"' in response.headers["content-disposition"]
    assert "Export title" in response.text
    assert "assistant export content" in response.text


def test_export_json_returns_conversation_payload():
    store = api_module._agent_store
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    user = store.append_message(session_id, role="user", content="json user")
    assistant = store.append_message(session_id, role="assistant", content="json assistant")

    client = TestClient(api_module.app)
    response = client.get(f"/api/sessions/{session_id}/export?format=json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload["session"]["id"] == session_id
    assert [message["id"] for message in payload["messages"]] == [user.id, assistant.id]
    assert payload["messages"][0]["content"] == "json user"
    assert payload["messages"][1]["content"] == "json assistant"
