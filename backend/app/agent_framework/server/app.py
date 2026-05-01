from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, Header, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from ..agent import build_agent_graph
from ..api_handlers.approvals import approve_action_impl, reject_action_impl
from ..api_handlers.attachments import get_attachment_impl, upload_attachment_impl
from ..api_handlers.knowledge import (
    apply_skill_proposal_impl,
    compact_session_impl,
    confirm_memory_impl,
    create_memory_proposal_impl,
    create_skill_proposal_impl,
    export_markdown_memories_impl,
    get_context_pact_impl,
    import_markdown_memory_seed_impl,
    list_skills_impl,
    patch_context_pact_impl,
    read_skill_impl,
    reject_skill_proposal_impl,
    search_memory_impl,
    search_messages_impl,
)
from ..api_handlers.messages import edit_message_impl, regenerate_message_impl, rerun_message_impl
from ..api_handlers.prompts import (
    create_prompt_impl,
    delete_prompt_impl,
    list_prompts_impl,
    update_prompt_impl,
)
from ..api_handlers.runs import (
    cancel_run_impl,
    chat_stream_impl,
    create_run_impl,
    get_run_impl,
    get_run_replay_impl,
    stop_session_impl,
    stream_run_events_impl,
)
from ..api_handlers.sessions import (
    create_session_impl,
    export_session_impl,
    get_session_impl,
    get_shared_session_impl,
    list_sessions_impl,
    patch_session_impl,
    revoke_session_share_impl,
    share_session_impl,
)
from ..paths import DATA_ROOT
from ..runtime import RunManager, runtime_health
from ..runtime.attachments import _attachment_store
from ..runtime.checkpointing import create_async_checkpointer
from ..storage import get_agent_store
from ..tool_runtime import create_default_registry
from . import (
    ChatStreamRequest,
    CompactSessionRequest,
    ContextPactPatchRequest,
    CreatePromptRequest,
    CreateSessionRequest,
    CreateSessionResponse,
    MemoryProposalRequest,
    MemorySearchResponse,
    MessageEditRequest,
    PromptItem,
    RegenerateMessageRequest,
    RerunMessageRequest,
    RunCreateRequest,
    RunCreateResponse,
    SessionDetail,
    SessionListItem,
    SessionPatchRequest,
    SkillProposalRequest,
    StopSessionRequest,
    UpdatePromptRequest,
)


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
    if os.getenv("TOMMY_MAINTENANCE_DISABLED", "").strip().lower() not in {"1", "true", "yes"}:
        from ..observability import MaintenanceScheduler, default_maintenance_jobs

        _maintenance_scheduler = MaintenanceScheduler(jobs=default_maintenance_jobs(_agent_store))
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
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
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
    return create_session_impl(_agent_store, request)


@app.get("/api/sessions")
async def list_sessions(agent_id: str = "default") -> dict[str, list[SessionListItem]]:
    return list_sessions_impl(_agent_store, agent_id)


@app.patch("/api/sessions/{session_id}")
async def patch_session(session_id: str, request: SessionPatchRequest) -> SessionListItem:
    return patch_session_impl(_agent_store, session_id, request)


@app.get("/api/sessions/{session_id}/export")
async def export_session(
    session_id: str,
    format: str = Query(default="md", pattern="^(md|json)$"),
) -> Response:
    return export_session_impl(_agent_store, session_id, format)


@app.post("/api/sessions/{session_id}/share")
async def share_session(session_id: str) -> dict[str, str]:
    return share_session_impl(_agent_store, session_id)


@app.delete("/api/sessions/{session_id}/share")
async def revoke_session_share(session_id: str) -> dict[str, str]:
    return revoke_session_share_impl(_agent_store, session_id)


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> SessionDetail:
    return await get_session_impl(_agent_store, _run_manager, session_id)


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    _agent_store.delete_session(session_id)
    checkpointer = _graph.checkpointer if _graph is not None else await create_async_checkpointer()
    try:
        await checkpointer.adelete_thread(session_id)
    except Exception:
        pass
    return {"status": "deleted"}


@app.get("/share/{token}")
async def get_shared_session(token: str) -> dict[str, Any]:
    return get_shared_session_impl(_agent_store, token)


@app.get("/api/prompts")
async def list_prompts(x_user_id: str = Header(default="")) -> dict[str, list[PromptItem]]:
    return list_prompts_impl(_agent_store, x_user_id)


@app.post("/api/prompts")
async def create_prompt(
    request: CreatePromptRequest,
    x_user_id: str = Header(default=""),
) -> PromptItem:
    return create_prompt_impl(_agent_store, request, x_user_id)


@app.patch("/api/prompts/{prompt_id}")
async def update_prompt(
    prompt_id: str,
    request: UpdatePromptRequest,
    x_user_id: str = Header(default=""),
) -> PromptItem:
    return update_prompt_impl(_agent_store, prompt_id, request, x_user_id)


@app.delete("/api/prompts/{prompt_id}")
async def delete_prompt(prompt_id: str, x_user_id: str = Header(default="")) -> dict[str, bool]:
    return delete_prompt_impl(_agent_store, prompt_id, x_user_id)


@app.post("/api/attachments")
async def upload_attachment(
    session_id: Annotated[str, Form(...)],
    file: Annotated[UploadFile, File(...)],
) -> dict[str, Any]:
    return await upload_attachment_impl(_agent_store, _attachment_store, session_id, file)


@app.get("/api/attachments/{attachment_id}")
async def get_attachment(attachment_id: str) -> Response:
    return get_attachment_impl(_attachment_store, attachment_id)


@app.patch("/api/messages/{message_id}")
async def edit_message(message_id: str, request: MessageEditRequest) -> dict[str, Any]:
    return edit_message_impl(_agent_store, message_id, request)


@app.post("/api/messages/{message_id}/rerun")
async def rerun_message(message_id: str, request: RerunMessageRequest) -> dict[str, Any]:
    return await rerun_message_impl(_agent_store, _run_manager, message_id, request)


@app.post("/api/messages/{message_id}/regenerate")
async def regenerate_message(message_id: str, request: RegenerateMessageRequest) -> dict[str, Any]:
    return await regenerate_message_impl(_agent_store, _run_manager, message_id, request)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatStreamRequest) -> StreamingResponse:
    return await chat_stream_impl(_run_manager, request)


@app.post("/api/runs")
async def create_run(request: RunCreateRequest) -> RunCreateResponse:
    return await create_run_impl(_run_manager, request)


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    return get_run_impl(_agent_store, run_id)


@app.get("/api/runs/{run_id}/replay")
async def get_run_replay(run_id: str) -> dict[str, Any]:
    return get_run_replay_impl(_agent_store, run_id)


@app.get("/api/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    after_sequence: int | None = None,
) -> StreamingResponse:
    return await stream_run_events_impl(_agent_store, _run_manager, run_id, after_sequence)


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict[str, Any]:
    return await cancel_run_impl(_run_manager, run_id)


@app.post("/api/sessions/{session_id}/stop")
async def stop_session(
    session_id: str,
    request: StopSessionRequest | None = None,
) -> dict[str, Any]:
    return await stop_session_impl(_agent_store, _run_manager, session_id, request)


@app.get("/api/search")
async def search_messages(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, list[dict[str, Any]]]:
    return search_messages_impl(_agent_store, q, limit)


@app.get("/api/memory")
async def search_memory(
    query: str, agent_id: str = "default", limit: int = 5
) -> MemorySearchResponse:
    return search_memory_impl(_agent_store, query, agent_id, limit)


@app.post("/api/memory/proposals")
async def create_memory_proposal(request: MemoryProposalRequest) -> dict[str, Any]:
    return create_memory_proposal_impl(_agent_store, request)


@app.post("/api/memory/{memory_id}/confirm")
async def confirm_memory(memory_id: str, agent_id: str = "default") -> dict[str, Any]:
    return confirm_memory_impl(_agent_store, memory_id, agent_id)


@app.post("/api/memory/import-markdown")
async def import_markdown_memory_seed(agent_id: str = "default") -> dict[str, Any]:
    return import_markdown_memory_seed_impl(_agent_store, agent_id)


@app.post("/api/memory/export-markdown")
async def export_markdown_memories(agent_id: str = "default") -> dict[str, Any]:
    return export_markdown_memories_impl(_agent_store, agent_id)


@app.post("/api/skills/proposals")
async def create_skill_proposal(request: SkillProposalRequest) -> dict[str, Any]:
    return create_skill_proposal_impl(_agent_store, request)


@app.get("/api/skills")
async def list_skills(agent_id: str = "default") -> dict[str, Any]:
    return list_skills_impl(_agent_store, agent_id)


@app.post("/api/skills/proposals/{proposal_id}/apply")
async def apply_skill_proposal(proposal_id: str, agent_id: str = "default") -> dict[str, Any]:
    return apply_skill_proposal_impl(_agent_store, proposal_id, agent_id)


@app.post("/api/skills/proposals/{proposal_id}/reject")
async def reject_skill_proposal(proposal_id: str, agent_id: str = "default") -> dict[str, Any]:
    return reject_skill_proposal_impl(_agent_store, proposal_id, agent_id)


@app.get("/api/skills/{skill_path:path}")
async def read_skill(skill_path: str, agent_id: str = "default") -> dict[str, str]:
    return read_skill_impl(_agent_store, skill_path, agent_id)


@app.get("/api/sessions/{session_id}/context-pact")
async def get_context_pact(session_id: str, agent_id: str = "default") -> dict[str, Any]:
    return get_context_pact_impl(_agent_store, session_id, agent_id)


@app.patch("/api/sessions/{session_id}/context-pact")
async def patch_context_pact(session_id: str, request: ContextPactPatchRequest) -> dict[str, Any]:
    return patch_context_pact_impl(_agent_store, session_id, request)


@app.post("/api/sessions/{session_id}/compact")
async def compact_session(
    session_id: str,
    request: CompactSessionRequest | None = None,
) -> dict[str, Any]:
    return compact_session_impl(_agent_store, session_id, request)


@app.post("/api/approvals/{approval_id}/approve")
async def approve_action(approval_id: str, agent_id: str = "default") -> dict[str, Any]:
    return await approve_action_impl(
        _agent_store,
        create_default_registry(),
        approval_id,
        agent_id,
        run_manager=_run_manager,
    )


@app.post("/api/approvals/{approval_id}/reject")
async def reject_action(approval_id: str) -> dict[str, Any]:
    return reject_action_impl(_agent_store, approval_id)


@app.get("/health")
async def health() -> dict[str, Any]:
    return runtime_health(_agent_store)


def app_root() -> Path:
    return DATA_ROOT.parents[1]
