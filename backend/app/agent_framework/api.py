from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .agent import build_agent_graph
from .api_schemas import (
    ChatStreamRequest,
    CompactSessionRequest,
    ContextPactPatchRequest,
    CreateSessionRequest,
    CreateSessionResponse,
    MemoryProposalRequest,
    MemorySearchResponse,
    RunCreateRequest,
    RunCreateResponse,
    SessionDetail,
    SessionListItem,
    SkillProposalRequest,
    StopSessionRequest,
)
from .approvals import execute_approved_action
from .checkpointing import create_async_checkpointer
from .compaction import compact_transcript_records
from .context import merge_context_pact, normalize_context_pact
from .events import format_sse
from .local_memory import LocalMemoryStore
from .paths import DATA_ROOT
from .runs import RunManager
from .runtime import RunCreatePayload, runtime_health
from .skills import SkillCatalog, SkillProposal
from .storage import get_agent_store
from .tools import create_default_registry


def cors_origins() -> list[str]:
    configured = os.getenv("FRONTEND_CORS_ORIGINS", "")
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    if origins:
        return origins
    return ["http://localhost:3000", "http://127.0.0.1:3000"]


_graph = None
_agent_store = get_agent_store()


async def get_graph():
    global _graph
    if _graph is None:
        _graph = build_agent_graph(
            checkpointer=await create_async_checkpointer(),
            async_model=True,
        )
    return _graph


_run_manager = RunManager(store=_agent_store, graph_factory=get_graph)


_maintenance_scheduler: Any | None = None


@asynccontextmanager
async def _app_lifespan(app: FastAPI):
    global _maintenance_scheduler
    await _run_manager.reconcile_orphan_inflight_runs()
    if os.getenv("TOMMY_MAINTENANCE_DISABLED", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        from .observability import MaintenanceScheduler, default_maintenance_jobs

        _maintenance_scheduler = MaintenanceScheduler(
            jobs=default_maintenance_jobs(_agent_store)
        )
        await _maintenance_scheduler.start()
    try:
        yield
    finally:
        if _maintenance_scheduler is not None:
            await _maintenance_scheduler.stop()


app = FastAPI(title="Tommy Agent Framework", version="0.1.0", lifespan=_app_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_origin_regex=(
        r"^https?://("
        r"localhost|127\.0\.0\.1|0\.0\.0\.0|"
        r"192\.168\.\d{1,3}\.\d{1,3}|"
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        r")(:\d+)?$"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/sessions")
async def create_session(request: CreateSessionRequest | None = None) -> CreateSessionResponse:
    payload = request or CreateSessionRequest()
    session_id = _agent_store.create_session(
        agent_id=payload.agent_id,
        title=payload.title,
        metadata=payload.metadata,
    )
    return CreateSessionResponse(session_id=session_id)


@app.get("/api/sessions")
async def list_sessions(agent_id: str = "default") -> dict[str, list[SessionListItem]]:
    return {
        "sessions": [
            SessionListItem(
                id=row["id"],
                title=row["title"],
                preview=row["preview"],
                summary=row["summary"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in _agent_store.list_sessions(agent_id=agent_id)
        ]
    }


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> SessionDetail:
    session = _agent_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await _run_manager.reconcile_orphan_inflight_runs(session_id)
    messages = [
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "metadata": message.metadata,
            "position": message.position,
            "created_at": message.created_at,
        }
        for message in _agent_store.list_messages(session_id)
    ]
    return SessionDetail(
        session=session,
        messages=messages,
        run_events=_agent_store.list_run_events(session_id),
        tool_calls=_agent_store.list_tool_calls(session_id),
        latest_run=_agent_store.get_latest_run(session_id),
        active_run=_agent_store.get_active_run(session_id),
        runs=_agent_store.list_runs(session_id),
        context_pact=normalize_context_pact(
            _agent_store.get_context_pact(session_id, agent_id=session.get("agent_id", "default"))
        ),
        skill_proposals=_agent_store.list_skill_proposals(
            agent_id=session.get("agent_id", "default"),
            status="proposed",
        ),
        memory_proposals=_agent_store.list_memories(
            agent_id=session.get("agent_id", "default"),
            status="proposed",
        ),
        compaction_runs=_agent_store.list_compaction_runs(session_id),
        pending_approvals=_agent_store.list_approval_requests(
            session_id=session_id,
            status="pending",
        ),
        skills=[
            {
                "name": skill.name,
                "path": skill.path,
                "description": skill.description,
                "updated_at": skill.updated_at,
            }
            for skill in SkillCatalog(
                agent_id=session.get("agent_id", "default"),
                store=_agent_store,
            ).list_skills()
        ],
    )


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    _agent_store.delete_session(session_id)
    checkpointer = _graph.checkpointer if _graph is not None else await create_async_checkpointer()
    try:
        await checkpointer.adelete_thread(session_id)
    except Exception:
        pass
    return {"status": "deleted"}


@app.post("/api/chat/stream")
async def chat_stream(request: ChatStreamRequest) -> StreamingResponse:
    """Legacy streaming endpoint backed by the run lifecycle APIs."""
    meta = dict(request.metadata)
    meta["transport"] = "chat_stream"
    payload = RunCreatePayload(
        session_id=request.session_id,
        message=request.message,
        agent_id=request.agent_id,
        metadata=meta,
        history=[
            {"role": item.role, "content": item.content}
            for item in request.history
            if item.content
        ],
        reset_thread=request.reset_thread,
    )
    run = await _run_manager.create_and_start_run(payload)
    rid = str(run["id"])

    async def event_iterator() -> AsyncIterator[str]:
        async for event in _run_manager.stream_run_events(rid):
            yield format_sse(event)

    return StreamingResponse(
        event_iterator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/runs")
async def create_run(request: RunCreateRequest) -> RunCreateResponse:
    run = await _run_manager.create_and_start_run(
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
            reset_thread=request.reset_thread,
        )
    )
    return RunCreateResponse(run_id=str(run["id"]), status=str(run["status"]))


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    run = _agent_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run": run}


@app.get("/api/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    after_sequence: int | None = None,
) -> StreamingResponse:
    run = _agent_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await _run_manager.reconcile_orphan_inflight_runs(str(run["session_id"]))

    async def event_iterator() -> AsyncIterator[str]:
        async for event in _run_manager.stream_run_events(run_id, after_sequence=after_sequence):
            yield format_sse(event)

    return StreamingResponse(
        event_iterator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict[str, Any]:
    run = await _run_manager.cancel_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run": run}


@app.post("/api/sessions/{session_id}/stop")
async def stop_session(
    session_id: str,
    request: StopSessionRequest | None = None,
) -> dict[str, Any]:
    payload = request or StopSessionRequest()
    await _run_manager.reconcile_orphan_inflight_runs(session_id)
    runs = _agent_store.request_run_stop(
        session_id,
        run_id=payload.run_id,
        reason=payload.reason,
    )
    run_cancelled = None
    target_run_id = payload.run_id
    if target_run_id is None:
        active_run = _agent_store.get_active_run(session_id)
        target_run_id = str(active_run["id"]) if active_run else None
    if target_run_id:
        run_cancelled = await _run_manager.cancel_run(target_run_id)
    for run in runs:
        _agent_store.append_run_event(
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


@app.get("/api/memory")
async def search_memory(
    query: str,
    agent_id: str = "default",
    limit: int = 5,
) -> MemorySearchResponse:
    results = [
        {"path": item["id"], "snippet": item["content"]}
        for item in _agent_store.search_memories(agent_id=agent_id, query=query, limit=limit)
    ]
    if not results:
        memory_store = LocalMemoryStore(agent_id=agent_id)
        results = memory_store.search(query, limit=limit)
    return MemorySearchResponse(results=results)


@app.post("/api/memory/proposals")
async def create_memory_proposal(request: MemoryProposalRequest) -> dict[str, Any]:
    proposal = _agent_store.create_memory(
        agent_id=request.agent_id,
        content=request.content,
        status="proposed",
        source_session_id=request.session_id,
        metadata=request.metadata,
    )
    return {"proposal": proposal}


@app.post("/api/memory/{memory_id}/confirm")
async def confirm_memory(memory_id: str, agent_id: str = "default") -> dict[str, Any]:
    memory = _agent_store.confirm_memory(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory proposal not found")
    memory_store = LocalMemoryStore(agent_id=agent_id)
    memory_store.append_daily_memory(memory["content"])
    memory_file = DATA_ROOT / agent_id / "MEMORY.md"
    with memory_file.open("a", encoding="utf-8") as handle:
        handle.write(f"\n- {memory['content']}\n")
    return {"memory": memory}


@app.post("/api/skills/proposals")
async def create_skill_proposal(request: SkillProposalRequest) -> dict[str, Any]:
    allow_auto_apply = bool(request.metadata.get("allow_auto_apply"))
    catalog = SkillCatalog(agent_id=request.agent_id, store=_agent_store)
    return catalog.create_proposal(
        SkillProposal(
            name=request.name,
            action=request.action,
            rationale=request.rationale,
            content=request.content,
            relative_path=request.relative_path,
            risks=request.risks,
            metadata=request.metadata,
        ),
        allow_auto_apply=allow_auto_apply,
    )


@app.get("/api/skills")
async def list_skills(agent_id: str = "default") -> dict[str, Any]:
    catalog = SkillCatalog(agent_id=agent_id, store=_agent_store)
    return {
        "skills": [
            {
                "name": skill.name,
                "path": skill.path,
                "description": skill.description,
                "updated_at": skill.updated_at,
            }
            for skill in catalog.list_skills()
        ],
        "proposals": catalog.list_proposals(status="proposed"),
    }


@app.post("/api/skills/proposals/{proposal_id}/apply")
async def apply_skill_proposal(proposal_id: str, agent_id: str = "default") -> dict[str, Any]:
    catalog = SkillCatalog(agent_id=agent_id, store=_agent_store)
    try:
        return {"proposal": catalog.apply_proposal(proposal_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/skills/proposals/{proposal_id}/reject")
async def reject_skill_proposal(proposal_id: str, agent_id: str = "default") -> dict[str, Any]:
    catalog = SkillCatalog(agent_id=agent_id, store=_agent_store)
    try:
        return {"proposal": catalog.reject_proposal(proposal_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/skills/{skill_path:path}")
async def read_skill(skill_path: str, agent_id: str = "default") -> dict[str, str]:
    catalog = SkillCatalog(agent_id=agent_id, store=_agent_store)
    try:
        return {
            "path": catalog.normalize_relative_path(skill_path),
            "content": catalog.read_skill(skill_path),
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/sessions/{session_id}/context-pact")
async def get_context_pact(session_id: str, agent_id: str = "default") -> dict[str, Any]:
    _agent_store.ensure_session(session_id, agent_id=agent_id)
    return {
        "pact": normalize_context_pact(
            _agent_store.get_context_pact(session_id, agent_id=agent_id)
        )
    }


@app.patch("/api/sessions/{session_id}/context-pact")
async def patch_context_pact(session_id: str, request: ContextPactPatchRequest) -> dict[str, Any]:
    _agent_store.ensure_session(session_id, agent_id=request.agent_id)
    current = _agent_store.get_context_pact(session_id, agent_id=request.agent_id)
    pact = merge_context_pact(
        current,
        {
            "summary": request.summary,
            "goals": request.goals,
            "constraints": request.constraints,
            "facts": request.facts,
            "open_questions": request.open_questions,
            "active_skills": request.active_skills,
        },
    )
    _agent_store.upsert_context_pact(session_id, agent_id=request.agent_id, pact=pact)
    return {"pact": pact}


@app.post("/api/sessions/{session_id}/compact")
async def compact_session(
    session_id: str,
    request: CompactSessionRequest | None = None,
) -> dict[str, Any]:
    payload = request or CompactSessionRequest()
    _agent_store.ensure_session(session_id, agent_id=payload.agent_id)
    messages = _agent_store.list_messages(session_id)
    result = compact_transcript_records(messages, keep_recent=payload.keep_recent)
    if not result.summary:
        return {"compaction": None, "pact": normalize_context_pact({})}
    _agent_store.set_session_summary(session_id, result.summary)
    current = _agent_store.get_context_pact(session_id, agent_id=payload.agent_id)
    pact = merge_context_pact(current, {"summary": result.summary})
    _agent_store.upsert_context_pact(session_id, agent_id=payload.agent_id, pact=pact)
    record = _agent_store.append_compaction_run(
        session_id,
        run_id=payload.run_id,
        summary=result.summary,
        message_count=len(messages),
        kept_messages=len(result.recent_tail),
        metadata={"trigger": "manual_api"},
    )
    return {"compaction": record, "pact": pact}


@app.post("/api/approvals/{approval_id}/approve")
async def approve_action(approval_id: str, agent_id: str = "default") -> dict[str, Any]:
    approval = _agent_store.get_approval_request(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Approval is already {approval['status']}")

    run_id = str(approval["run_id"])
    session_id = str(approval["session_id"])
    if _agent_store.run_stop_requested(session_id=session_id, run_id=run_id):
        rejected = _agent_store.resolve_approval_request(
            approval_id,
            status="rejected",
            error="Run was stopped by user",
        )
        _agent_store.append_run_event(
            session_id,
            run_id=run_id,
            type="approval",
            label=f"运行已停止，未执行：{approval['tool_name']}",
            status="error",
            payload={"approval": rejected},
        )
        raise HTTPException(status_code=409, detail="Run was stopped; approval was not executed.")

    approved = _agent_store.resolve_approval_request(approval_id, status="approved")
    if approved is None:
        raise HTTPException(status_code=404, detail="Approval request not found")

    _agent_store.append_run_event(
        session_id,
        run_id=run_id,
        type="approval",
        label=f"审批通过：{approval['tool_name']}",
        status="done",
        payload={"approval": approved},
    )

    try:
        if _agent_store.run_stop_requested(session_id=session_id, run_id=run_id):
            raise RuntimeError("Run was stopped before the approved action could execute.")
        if approval["tool_name"] == "delegate_task":
            args = approval.get("args") or {}
            _agent_store.append_run_event(
                session_id,
                run_id=run_id,
                type="subagent",
                label=f"子 Agent {args.get('target_agent', 'researcher')} 启动",
                status="running",
                payload={
                    "approval": approval,
                    "target_agent": args.get("target_agent", "researcher"),
                },
            )
        result = execute_approved_action(
            approval,
            registry=create_default_registry(),
            context={"agent_id": agent_id},
        )
        executed = _agent_store.resolve_approval_request(
            approval_id,
            status="executed",
            result=result,
        )
        _agent_store.upsert_tool_call(
            session_id,
            run_id=run_id,
            tool_call_id=str(approval["tool_call_id"]),
            name=str(approval["tool_name"]),
            status="done",
            args=approval.get("args") or {},
            result=result,
        )
        if approval["tool_name"] == "delegate_task":
            args = approval.get("args") or {}
            _agent_store.append_run_event(
                session_id,
                run_id=run_id,
                type="subagent",
                label=f"子 Agent {args.get('target_agent', 'researcher')} 完成",
                status="done",
                payload={"approval": executed, "result": result},
            )
        _agent_store.append_run_event(
            session_id,
            run_id=run_id,
            type="approval",
            label=f"已执行：{approval['tool_name']}",
            status="done",
            payload={"approval": executed},
        )
        return {"approval": executed, "result": result}
    except Exception as exc:  # noqa: BLE001 - approval execution errors are user-visible.
        failed = _agent_store.resolve_approval_request(
            approval_id,
            status="failed",
            error=str(exc),
        )
        _agent_store.append_run_event(
            session_id,
            run_id=run_id,
            type="approval",
            label=f"执行失败：{approval['tool_name']}",
            status="error",
            payload={"approval": failed, "error": str(exc)},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/approvals/{approval_id}/reject")
async def reject_action(approval_id: str) -> dict[str, Any]:
    approval = _agent_store.get_approval_request(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Approval is already {approval['status']}")
    rejected = _agent_store.resolve_approval_request(
        approval_id,
        status="rejected",
        error="Rejected by user",
    )
    _agent_store.append_run_event(
        str(approval["session_id"]),
        run_id=str(approval["run_id"]),
        type="approval",
        label=f"已拒绝：{approval['tool_name']}",
        status="error",
        payload={"approval": rejected},
    )
    return {"approval": rejected}


@app.get("/health")
async def health() -> dict[str, Any]:
    return runtime_health(_agent_store)


def app_root() -> Path:
    return DATA_ROOT.parents[1]
