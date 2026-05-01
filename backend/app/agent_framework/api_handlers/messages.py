from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ..runtime import RunCreatePayload
from ..server import MessageEditRequest, RegenerateMessageRequest, RerunMessageRequest
from .common import (
    find_parent_user_message,
    get_message_or_404,
    message_to_dict,
    require_message_role,
    stored_attachment_refs,
)


def edit_message_impl(store, message_id: str, request: MessageEditRequest) -> dict[str, Any]:
    message, _session = get_message_or_404(store, message_id)
    require_message_role(message, "user")
    updated = store.update_message(message_id, content=request.content)
    if updated is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return message_to_dict(updated)


async def rerun_message_impl(store, run_manager, message_id: str, request: RerunMessageRequest):
    target_message, session = get_message_or_404(store, message_id)
    require_message_role(target_message, "user")
    if request.content is not None:
        updated = store.update_message(message_id, content=request.content)
        if updated is None:
            raise HTTPException(status_code=404, detail="Message not found")
        target_message = updated

    store.delete_messages_after(target_message.session_id, target_message.position)
    metadata = {**request.metadata, "target_user_message_id": target_message.id, "rerun": True}
    return await run_manager.create_and_start_run(
        RunCreatePayload(
            session_id=target_message.session_id,
            message=target_message.content,
            agent_id=str(session.get("agent_id") or request.agent_id),
            metadata=metadata,
            attachments=stored_attachment_refs(target_message),
            skip_user_persist=True,
            reset_thread=True,
            idempotency_key=request.idempotency_key,
        )
    )


async def regenerate_message_impl(
    store,
    run_manager,
    message_id: str,
    request: RegenerateMessageRequest,
):
    target_message, session = get_message_or_404(store, message_id)
    require_message_role(target_message, "assistant")
    parent_user = find_parent_user_message(
        store, target_message.session_id, target_message.position
    )
    store.delete_messages_after(parent_user.session_id, parent_user.position)
    metadata = {**request.metadata, "target_user_message_id": parent_user.id, "regenerate": True}
    return await run_manager.create_and_start_run(
        RunCreatePayload(
            session_id=parent_user.session_id,
            message=parent_user.content,
            agent_id=str(session.get("agent_id") or request.agent_id),
            metadata=metadata,
            attachments=stored_attachment_refs(parent_user),
            skip_user_persist=True,
            reset_thread=True,
            idempotency_key=request.idempotency_key,
        )
    )
