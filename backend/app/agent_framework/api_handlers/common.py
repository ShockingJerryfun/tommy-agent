from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from ..server import SessionListItem


def message_to_dict(message) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "metadata": message.metadata,
        "position": message.position,
        "created_at": message.created_at,
    }


def stored_attachment_refs(message) -> list[dict[str, Any]]:
    attachments = (message.metadata or {}).get("attachments")
    return attachments if isinstance(attachments, list) else []


def session_list_item(row: dict[str, Any]) -> SessionListItem:
    return SessionListItem(
        id=row["id"],
        title=row["title"],
        preview=row["preview"],
        summary=row["summary"],
        pinned=bool(row.get("pinned", False)),
        archived=bool(row.get("archived", False)),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def export_slug(title: str, session_id: str) -> str:
    slug = re.sub(r"\W+", "-", title.lower()).strip("-")[:64].strip("-")
    return slug or f"session-{session_id[-6:]}"


def render_markdown_export(session: dict[str, Any], messages: list[Any]) -> str:
    parts = [
        f"# {session['title']}",
        "",
        f"> Exported on {datetime.now(UTC).isoformat()}",
        "",
    ]
    for message in messages:
        label = "You" if message.role == "user" else "Tommy"
        parts.extend(
            [
                "---",
                "",
                f"**{label}** ({message.created_at})",
                "",
                message.content,
                "",
            ]
        )
    return "\n".join(parts)


def run_summary(metric: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": metric["run_id"],
        "model": metric.get("model"),
        "prompt_tokens": metric.get("prompt_tokens"),
        "completion_tokens": metric.get("completion_tokens"),
        "total_tokens": metric.get("total_tokens"),
        "latency_ms": metric.get("duration_ms"),
        "finish_reason": metric.get("finish_reason"),
        "started_at": metric.get("started_at"),
        "finished_at": metric.get("finished_at"),
    }


def attach_run_summaries(
    messages: list[dict[str, Any]],
    metrics_by_run_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    for message in messages:
        if message.get("role") != "assistant":
            continue
        metadata = message.get("metadata")
        if not isinstance(metadata, dict):
            continue
        run_id = metadata.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            continue
        metric = metrics_by_run_id.get(run_id)
        if metric is not None:
            message["run_summary"] = run_summary(metric)
    return messages


def get_message_or_404(store, message_id: str):
    message = store.get_message(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    session = store.get_session(message.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return message, session


def require_message_role(message, expected_role: str) -> None:
    if message.role != expected_role:
        raise HTTPException(status_code=422, detail=f"Expected {expected_role} message")


def find_parent_user_message(store, session_id: str, before_position: int):
    candidates = [
        message
        for message in store.list_messages(session_id)
        if message.role == "user" and message.position < before_position
    ]
    if not candidates:
        raise HTTPException(status_code=422, detail="Assistant message has no parent user")
    return candidates[-1]
