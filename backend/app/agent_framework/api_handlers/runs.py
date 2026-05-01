from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from ..observability import replay_run_events
from ..runtime import RunCreatePayload
from ..runtime.events import format_sse
from ..server import ChatStreamRequest, RunCreateRequest, RunCreateResponse, StopSessionRequest


async def chat_stream_impl(run_manager, request: ChatStreamRequest) -> StreamingResponse:
    meta = dict(request.metadata)
    meta["transport"] = "chat_stream"
    payload = RunCreatePayload(
        session_id=request.session_id,
        message=request.message,
        agent_id=request.agent_id,
        metadata=meta,
        history=[
            {"role": item.role, "content": item.content} for item in request.history if item.content
        ],
        attachments=request.attachments,
        reset_thread=request.reset_thread,
        idempotency_key=request.idempotency_key,
    )
    run = await run_manager.create_and_start_run(payload)
    run_id = str(run["id"])

    async def event_iterator() -> AsyncIterator[str]:
        async for event in run_manager.stream_run_events(run_id):
            yield format_sse(event)

    return StreamingResponse(
        event_iterator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def create_run_impl(run_manager, request: RunCreateRequest) -> RunCreateResponse:
    run = await run_manager.create_and_start_run(
        RunCreatePayload(
            session_id=request.session_id,
            message=request.message,
            agent_id=request.agent_id,
            metadata=request.metadata,
            history=[
                {"role": item.role, "content": item.content}
                for item in request.history
                if item.content
            ],
            attachments=request.attachments,
            reset_thread=request.reset_thread,
            idempotency_key=request.idempotency_key,
        )
    )
    return RunCreateResponse(run_id=str(run["id"]), status=str(run["status"]))


def get_run_impl(store, run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run": run}


def get_run_replay_impl(store, run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"replay": replay_run_events(store, run_id=run_id).as_dict()}


async def stream_run_events_impl(
    store,
    run_manager,
    run_id: str,
    after_sequence: int | None,
) -> StreamingResponse:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await run_manager.reconcile_orphan_inflight_runs(str(run["session_id"]))

    async def event_iterator() -> AsyncIterator[str]:
        async for event in run_manager.stream_run_events(run_id, after_sequence=after_sequence):
            yield format_sse(event)

    return StreamingResponse(
        event_iterator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def cancel_run_impl(run_manager, run_id: str) -> dict[str, Any]:
    run = await run_manager.cancel_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run": run}


async def stop_session_impl(
    store,
    run_manager,
    session_id: str,
    request: StopSessionRequest | None,
) -> dict[str, Any]:
    payload = request or StopSessionRequest()
    await run_manager.reconcile_orphan_inflight_runs(session_id)
    runs = store.request_run_stop(session_id, run_id=payload.run_id, reason=payload.reason)
    run_cancelled = None
    target_run_id = payload.run_id
    if target_run_id is None:
        active_run = store.get_active_run(session_id)
        target_run_id = str(active_run["id"]) if active_run else None
    if target_run_id:
        run_cancelled = await run_manager.cancel_run(target_run_id)
    for run in runs:
        store.append_run_event(
            session_id,
            run_id=str(run["id"]),
            type="done",
            label="已停止",
            status="done",
            payload={"status": "stopped", "reason": payload.reason},
        )
    return {
        "status": "stopping" if runs or run_cancelled else "idle",
        "runs": runs,
        "run": run_cancelled,
    }
