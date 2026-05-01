from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agent_framework.runtime import (
    MAX_ATTACHMENT_BYTES,
    AttachmentStore,
    RunCreatePayload,
    RunManager,
)
from app.agent_framework.runtime import manager as runs_module
from app.agent_framework.server import app as api_module

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c6360000002000100"
    "05fe02fea5579a0000000049454e44ae426082"
)


def _patch_attachment_store(monkeypatch: pytest.MonkeyPatch, tmp_path) -> AttachmentStore:
    store = AttachmentStore(root=tmp_path / "attachments")
    monkeypatch.setattr(api_module, "_attachment_store", store)
    monkeypatch.setattr(runs_module, "_attachment_store", store)
    return store


def test_upload_and_fetch_image(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch_attachment_store(monkeypatch, tmp_path)
    store = api_module._agent_store
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    client = TestClient(api_module.app)

    response = client.post(
        "/api/attachments",
        data={"session_id": session_id},
        files={"file": ("pixel.png", PNG_1X1, "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mime"] == "image/png"
    assert payload["byte_size"] == len(PNG_1X1)
    assert payload["name"] == "pixel.png"
    assert payload["thumbnail_url"] == f"/api/attachments/{payload['id']}"

    fetched = client.get(payload["thumbnail_url"])
    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == "image/png"
    assert fetched.headers["cache-control"] == "private, max-age=300"
    assert fetched.content == PNG_1X1


def test_upload_rejects_unsupported_mime(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch_attachment_store(monkeypatch, tmp_path)
    store = api_module._agent_store
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    client = TestClient(api_module.app)

    response = client.post(
        "/api/attachments",
        data={"session_id": session_id},
        files={"file": ("page.html", b"<p>no</p>", "text/html")},
    )

    assert response.status_code == 415


def test_upload_rejects_oversize(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch_attachment_store(monkeypatch, tmp_path)
    store = api_module._agent_store
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    client = TestClient(api_module.app)

    response = client.post(
        "/api/attachments",
        data={"session_id": session_id},
        files={"file": ("big.txt", b"x" * (MAX_ATTACHMENT_BYTES + 1), "text/plain")},
    )

    assert response.status_code == 413


class CaptureRuntime:
    def __init__(self) -> None:
        self.inputs = None

    async def reset_thread(self, session_id: str) -> None:
        return None

    async def stream(self, session_id: str, inputs):
        self.inputs = inputs
        if False:
            yield None


@pytest.mark.asyncio
async def test_run_payload_with_image_attachment_renders_text_reference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    attachment_store = _patch_attachment_store(monkeypatch, tmp_path)
    store = api_module._agent_store
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    saved = attachment_store.save(
        session_id,
        filename="pixel.png",
        mime="image/png",
        data=PNG_1X1,
    )
    runtime = CaptureRuntime()
    manager = RunManager(store=store, graph_runtime=runtime)
    run = store.create_run(session_id=session_id, agent_id="default", input="what is this?")

    await manager.execute_run(
        str(run["id"]),
        RunCreatePayload(
            session_id=session_id,
            message="what is this?",
            attachments=[
                {
                    "id": saved["id"],
                    "mime": saved["mime"],
                    "byte_size": saved["byte_size"],
                    "name": saved["name"],
                }
            ],
        ),
    )

    content = runtime.inputs["messages"][-1].content
    assert isinstance(content, list)
    references = [part.get("text", "") for part in content if part.get("type") == "text"]
    assert any("/api/attachments/" in text and "pixel.png" in text for text in references)
    assert not any(part.get("type") == "image_url" for part in content)


@pytest.mark.asyncio
async def test_run_payload_with_pdf_attachment_renders_text_reference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    attachment_store = _patch_attachment_store(monkeypatch, tmp_path)
    store = api_module._agent_store
    store.reset_for_tests()
    session_id = store.create_session(agent_id="default")
    saved = attachment_store.save(
        session_id,
        filename="brief.pdf",
        mime="application/pdf",
        data=b"%PDF-1.4\n%",
    )
    runtime = CaptureRuntime()
    manager = RunManager(store=store, graph_runtime=runtime)
    run = store.create_run(session_id=session_id, agent_id="default", input="summarize")

    await manager.execute_run(
        str(run["id"]),
        RunCreatePayload(
            session_id=session_id,
            message="summarize",
            attachments=[
                {
                    "id": saved["id"],
                    "mime": saved["mime"],
                    "byte_size": saved["byte_size"],
                    "name": saved["name"],
                }
            ],
        ),
    )

    content = runtime.inputs["messages"][-1].content
    assert isinstance(content, list)
    references = [part.get("text", "") for part in content if part.get("type") == "text"]
    assert any("/api/attachments/" in text and "brief.pdf" in text for text in references)
