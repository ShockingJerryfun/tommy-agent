from __future__ import annotations

from fastapi.testclient import TestClient

from app.agent_framework.server import app as api_module


def test_list_includes_builtins() -> None:
    store = api_module._agent_store
    store.reset_for_tests()
    client = TestClient(api_module.app)

    response = client.get("/api/prompts")

    assert response.status_code == 200
    shortcuts = {prompt["shortcut"] for prompt in response.json()["prompts"]}
    assert {"summarize", "translate", "explain-code", "improve-writing"} <= shortcuts


def test_user_can_create_update_delete_own_prompt() -> None:
    store = api_module._agent_store
    store.reset_for_tests()
    client = TestClient(api_module.app)
    headers = {"X-User-Id": "alice"}

    created = client.post(
        "/api/prompts",
        headers=headers,
        json={"name": "Tone", "body": "Make this warmer", "shortcut": "tone"},
    )
    assert created.status_code == 200
    prompt_id = created.json()["id"]

    updated = client.patch(
        f"/api/prompts/{prompt_id}",
        headers=headers,
        json={"name": "Friendly tone", "shortcut": "friendly"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Friendly tone"
    assert updated.json()["body"] == "Make this warmer"
    assert updated.json()["shortcut"] == "friendly"

    deleted = client.delete(f"/api/prompts/{prompt_id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}
    missing = client.patch(
        f"/api/prompts/{prompt_id}",
        headers=headers,
        json={"name": "x"},
    )
    assert missing.status_code == 404


def test_cannot_delete_builtin() -> None:
    store = api_module._agent_store
    store.reset_for_tests()
    client = TestClient(api_module.app)

    response = client.delete("/api/prompts/prompt-builtin-summarize")

    assert response.status_code == 403


def test_cannot_modify_other_users_prompt() -> None:
    store = api_module._agent_store
    store.reset_for_tests()
    client = TestClient(api_module.app)

    created = client.post(
        "/api/prompts",
        headers={"X-User-Id": "a"},
        json={"name": "A", "body": "Body", "shortcut": "mine"},
    )
    assert created.status_code == 200

    response = client.patch(
        f"/api/prompts/{created.json()['id']}",
        headers={"X-User-Id": "b"},
        json={"name": "B"},
    )

    assert response.status_code == 403


def test_shortcut_uniqueness_per_owner() -> None:
    store = api_module._agent_store
    store.reset_for_tests()
    client = TestClient(api_module.app)
    headers = {"X-User-Id": "alice"}

    first = client.post(
        "/api/prompts",
        headers=headers,
        json={"name": "One", "body": "Body", "shortcut": "dupe"},
    )
    second = client.post(
        "/api/prompts",
        headers=headers,
        json={"name": "Two", "body": "Body", "shortcut": "dupe"},
    )

    assert first.status_code == 200
    assert second.status_code == 409
