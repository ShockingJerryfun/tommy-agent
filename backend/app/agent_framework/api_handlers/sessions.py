from __future__ import annotations

import json
import secrets
from typing import Any

from fastapi import HTTPException
from fastapi.responses import Response

from ..paths import DATA_ROOT
from ..prompt_context import normalize_context_pact
from ..server import (
    CreateSessionRequest,
    CreateSessionResponse,
    SessionDetail,
    SessionPatchRequest,
)
from ..skill_runtime import list_indexed_skill_summaries
from .common import (
    attach_run_summaries,
    export_slug,
    message_to_dict,
    render_markdown_export,
    session_list_item,
)


def create_session_impl(store, request: CreateSessionRequest | None) -> CreateSessionResponse:
    payload = request or CreateSessionRequest()
    session_id = store.create_session(
        agent_id=payload.agent_id,
        title=payload.title,
        metadata=payload.metadata,
    )
    return CreateSessionResponse(session_id=session_id)


def list_sessions_impl(store, agent_id: str) -> dict[str, list[Any]]:
    return {"sessions": [session_list_item(row) for row in store.list_sessions(agent_id=agent_id)]}


def patch_session_impl(store, session_id: str, request: SessionPatchRequest):
    updated = store.update_session_metadata(
        session_id,
        title=request.title,
        pinned=request.pinned,
        archived=request.archived,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session_list_item(updated)


def export_session_impl(store, session_id: str, format: str) -> Response:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = store.list_messages(session_id)
    slug = export_slug(str(session["title"]), session_id)
    if format == "json":
        payload = {
            "session": session,
            "messages": [message_to_dict(message) for message in messages],
        }
        return Response(
            content=json.dumps(payload, ensure_ascii=False, default=str),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{slug}.json"'},
        )
    return Response(
        content=render_markdown_export(session, messages),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{slug}.md"'},
    )


def share_session_impl(store, session_id: str) -> dict[str, str]:
    if store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    token = secrets.token_urlsafe(24)
    store.set_share_token(session_id, token)
    return {"token": token, "url": f"/share/{token}"}


def revoke_session_share_impl(store, session_id: str) -> dict[str, str]:
    if store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    store.set_share_token(session_id, None)
    return {"status": "revoked"}


async def get_session_impl(store, run_manager, session_id: str) -> SessionDetail:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await run_manager.reconcile_orphan_inflight_runs(session_id)
    messages = [message_to_dict(message) for message in store.list_messages(session_id)]
    metrics_by_run_id = {
        str(metric["run_id"]): metric for metric in store.list_run_metrics(session_id, limit=200)
    }
    attach_run_summaries(messages, metrics_by_run_id)
    agent_id = session.get("agent_id", "default")
    return SessionDetail(
        session=session,
        messages=messages,
        run_events=store.list_run_events(session_id),
        tool_calls=store.list_tool_calls(session_id),
        latest_run=store.get_latest_run(session_id),
        active_run=store.get_active_run(session_id),
        runs=store.list_runs(session_id),
        context_pact=normalize_context_pact(store.get_context_pact(session_id, agent_id=agent_id)),
        skill_proposals=store.list_skill_proposals(agent_id=agent_id, status="proposed"),
        memory_proposals=store.list_memories(agent_id=agent_id, status="proposed"),
        compaction_runs=store.list_compaction_runs(session_id),
        pending_approvals=store.list_approval_requests(session_id=session_id, status="pending"),
        skills=list_indexed_skill_summaries(
            store=store,
            agent_id=agent_id,
            skills_root=DATA_ROOT / agent_id / "skills",
        ),
    )


def get_shared_session_impl(store, token: str) -> dict[str, Any]:
    session = store.get_session_by_share_token(token)
    if session is None:
        raise HTTPException(status_code=404, detail="Shared conversation not found")
    return {
        "session": {
            "id": session["id"],
            "title": session["title"],
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
        },
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at,
            }
            for message in store.list_messages(str(session["id"]))
        ],
    }
