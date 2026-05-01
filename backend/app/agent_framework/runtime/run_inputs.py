from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from .attachments import _attachment_store
from .types import AttachmentRef, RunCreatePayload


def extract_memory_request(message: str) -> str | None:
    normalized = message.strip()
    prefixes = ("请记住", "记住", "帮我记住", "remember that", "please remember")
    for prefix in prefixes:
        if normalized.lower().startswith(prefix.lower()):
            return normalized[len(prefix) :].strip(" ：:，,。")
    return None


def normalize_attachment_refs(value: Any) -> list[AttachmentRef]:
    if not isinstance(value, list):
        return []
    refs: list[AttachmentRef] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        attachment_id = item.get("id")
        mime = item.get("mime")
        name = item.get("name")
        byte_size = item.get("byte_size")
        if (
            isinstance(attachment_id, str)
            and isinstance(mime, str)
            and isinstance(name, str)
            and isinstance(byte_size, int)
        ):
            refs.append({"id": attachment_id, "mime": mime, "byte_size": byte_size, "name": name})
    return refs


def build_user_message_content(
    message: str,
    attachments: list[AttachmentRef],
    *,
    attachment_store=_attachment_store,
) -> str | list[dict]:
    if not attachments:
        return message
    parts: list[dict] = []
    if message:
        parts.append({"type": "text", "text": message})
    for ref in attachments:
        path = attachment_store.path_for(ref["id"])
        if path is None:
            continue
        label = "Image attachment" if ref["mime"].startswith("image/") else "Attachment"
        parts.append(
            {
                "type": "text",
                "text": (
                    f"[{label}: {ref['name']} ({ref['mime']}, "
                    f"{ref['byte_size']} bytes) at /api/attachments/{ref['id']}]"
                ),
            }
        )
    return parts or message


def build_history_messages(
    store, payload: RunCreatePayload, *, attachment_store=_attachment_store
) -> list[Any]:
    if not payload.reset_thread:
        return []
    history_messages = []
    if payload.history:
        for item in payload.history:
            content = item.get("content") or ""
            if not content:
                continue
            message_cls = AIMessage if item.get("role") == "assistant" else HumanMessage
            history_messages.append(message_cls(content=content))
        return history_messages

    for item in store.list_messages(payload.session_id, limit=24):
        if not item.content or item.content == payload.message:
            continue
        if item.role == "assistant":
            history_messages.append(AIMessage(content=item.content))
        elif item.role == "user":
            history_messages.append(
                HumanMessage(
                    content=build_user_message_content(
                        item.content,
                        normalize_attachment_refs(item.metadata.get("attachments")),
                        attachment_store=attachment_store,
                    )
                )
            )
    return history_messages
