from __future__ import annotations

import json
from collections.abc import AsyncIterator
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

from .agent import build_agent_graph
from .approvals import execute_approved_action
from .compaction import compact_transcript_records, should_compact
from .context import merge_context_pact, normalize_context_pact
from .events import AgentEvent, done_event, error_event, format_sse, map_stream_part
from .memory import DATA_ROOT, LocalMemoryStore, build_thread_config, create_async_checkpointer
from .skills import SkillCatalog, SkillProposal
from .store import SQLiteAgentStore
from .tools import create_default_registry


class CreateSessionResponse(BaseModel):
    session_id: str


class CreateSessionRequest(BaseModel):
    agent_id: str = Field(default="default")
    title: str = Field(default="新对话")
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionListItem(BaseModel):
    id: str
    title: str
    preview: str
    summary: str = ""
    created_at: str
    updated_at: str


class SessionDetail(BaseModel):
    session: dict[str, Any]
    messages: list[dict[str, Any]]
    run_events: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    context_pact: dict[str, Any] = Field(default_factory=dict)
    skill_proposals: list[dict[str, Any]] = Field(default_factory=list)
    memory_proposals: list[dict[str, Any]] = Field(default_factory=list)
    compaction_runs: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[dict[str, Any]] = Field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = Field(default_factory=list)


class ChatStreamRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    agent_id: str = Field(default="default")
    metadata: dict[str, Any] = Field(default_factory=dict)
    history: list["ChatHistoryMessage"] = Field(default_factory=list)
    reset_thread: bool = Field(default=False)


class ChatHistoryMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(default="")


class MemorySearchResponse(BaseModel):
    results: list[dict[str, str]]


class MemoryProposalRequest(BaseModel):
    content: str = Field(..., min_length=1)
    agent_id: str = Field(default="default")
    session_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillProposalRequest(BaseModel):
    name: str = Field(..., min_length=1)
    action: str = Field(default="create", pattern="^(create|update)$")
    rationale: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    relative_path: str | None = None
    risks: list[str] = Field(default_factory=list)
    agent_id: str = Field(default="default")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextPactPatchRequest(BaseModel):
    agent_id: str = Field(default="default")
    summary: str | None = None
    goals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    active_skills: list[str] = Field(default_factory=list)


class CompactSessionRequest(BaseModel):
    agent_id: str = Field(default="default")
    run_id: str | None = None
    keep_recent: int = Field(default=18, ge=4, le=80)


def cors_origins() -> list[str]:
    configured = os.getenv("FRONTEND_CORS_ORIGINS", "")
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    if origins:
        return origins
    return ["http://localhost:3000", "http://127.0.0.1:3000"]


app = FastAPI(title="Tommy Agent Framework", version="0.1.0")
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
_graph = None
_agent_store = SQLiteAgentStore()


async def get_graph():
    global _graph
    if _graph is None:
        _graph = build_agent_graph(checkpointer=await create_async_checkpointer())
    return _graph


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


def _event_to_run_step(event: AgentEvent) -> tuple[str, str, str]:
    data = event.data
    if event.type == "tool_start":
        return "tool", f"{data.get('tool', '工具')} 运行中", "running"
    if event.type == "tool_end":
        failed = str(data.get("status", "ok")) == "error"
        return (
            "tool",
            f"{data.get('tool', '工具')} {'失败' if failed else '完成'}",
            "error" if failed else "done",
        )
    if event.type == "node_end":
        updates = data.get("updates") if isinstance(data.get("updates"), list) else []
        if "action" in updates:
            return "agent", "工具调用完成", "done"
        if "agent" in updates:
            return "agent", "回复已更新", "done"
        return "agent", "状态已更新", "done"
    if event.type == "error":
        return "error", "请求出错", "error"
    if event.type == "done":
        return "done", "完成", "done"
    if event.type == "skill":
        proposal = data.get("proposal") if isinstance(data.get("proposal"), dict) else {}
        label = f"Skill {proposal.get('name') or data.get('name') or 'proposal'}"
        return "skill", label, "done"
    if event.type == "pact":
        return "pact", "上下文 Pact 已更新", "done"
    if event.type == "delegate":
        return "delegate", f"委派给 {data.get('target_agent', 'agent')}", "running"
    if event.type == "compaction":
        return "compaction", "会话已压缩", "done"
    if event.type == "approval_pending":
        approval = data.get("approval") if isinstance(data.get("approval"), dict) else {}
        return "approval", f"等待审批：{approval.get('tool_name', '工具')}", "running"
    if event.type == "approval_resolved":
        approval = data.get("approval") if isinstance(data.get("approval"), dict) else {}
        failed = str(approval.get("status") or "") in {"failed", "rejected"}
        return "approval", "审批已处理", "error" if failed else "done"
    if event.type == "subagent_start":
        return "subagent", f"子 Agent {data.get('target_agent', '')} 启动", "running"
    if event.type == "subagent_end":
        return "subagent", f"子 Agent {data.get('target_agent', '')} 完成", "done"
    return "agent", event.type, "done"


def _extract_memory_request(message: str) -> str | None:
    normalized = message.strip()
    prefixes = ("请记住", "记住", "帮我记住", "remember that", "please remember")
    for prefix in prefixes:
        if normalized.lower().startswith(prefix.lower()):
            return normalized[len(prefix) :].strip(" ：:，,。")
    return None


async def _stream_chat(request: ChatStreamRequest) -> AsyncIterator[str]:
    memory_store = LocalMemoryStore(agent_id=request.agent_id)
    memory_store.ensure_layout()
    _agent_store.ensure_session(request.session_id, agent_id=request.agent_id)
    graph = await get_graph()
    if request.reset_thread:
        try:
            await graph.checkpointer.adelete_thread(request.session_id)
        except Exception:
            pass
        _agent_store.reset_session_content(
            request.session_id,
            messages=[
                {"role": item.role, "content": item.content}
                for item in request.history
                if item.content
            ],
        )

    run_id = f"run-{uuid4().hex}"
    memory_store.append_session_event(
        request.session_id,
        {"role": "user", "content": request.message},
    )
    _agent_store.append_message(
        request.session_id,
        role="user",
        content=request.message,
        metadata={
            "source": "chat_stream",
            "run_id": run_id,
            "frontend": request.metadata.get("frontend_settings"),
        },
    )
    memory_candidate = _extract_memory_request(request.message)
    if memory_candidate:
        proposal = _agent_store.create_memory(
            agent_id=request.agent_id,
            content=memory_candidate,
            status="proposed",
            source_session_id=request.session_id,
            metadata={"source": "explicit_user_request"},
        )
        memory_event = AgentEvent(
            type="memory",
            data={
                "status": "proposed",
                "proposal": proposal,
                "message": "已生成记忆提案，确认后才会写入长期记忆。",
            },
        )
        _agent_store.append_run_event(
            request.session_id,
            run_id=run_id,
            type="memory",
            label="记忆提案已创建",
            status="done",
            payload=memory_event.data,
        )
        yield format_sse(memory_event)
    stored_for_compaction = _agent_store.list_messages(request.session_id)
    recent_compactions = _agent_store.list_compaction_runs(request.session_id, limit=1)
    last_compacted_count = (
        int(recent_compactions[0].get("message_count") or 0)
        if recent_compactions
        else 0
    )
    if should_compact(stored_for_compaction, max_messages=48) and len(stored_for_compaction) >= last_compacted_count + 12:
        compaction = compact_transcript_records(stored_for_compaction, keep_recent=18)
        if compaction.summary:
            _agent_store.set_session_summary(request.session_id, compaction.summary)
            current_pact = _agent_store.get_context_pact(request.session_id, agent_id=request.agent_id)
            pact = merge_context_pact(current_pact, {"summary": compaction.summary})
            _agent_store.upsert_context_pact(request.session_id, agent_id=request.agent_id, pact=pact)
            record = _agent_store.append_compaction_run(
                request.session_id,
                run_id=run_id,
                summary=compaction.summary,
                message_count=len(stored_for_compaction),
                kept_messages=len(compaction.recent_tail),
                metadata={"trigger": "chat_stream_threshold"},
            )
            compaction_event = AgentEvent(
                type="compaction",
                data={"compaction": record, "pact": pact},
            )
            step_type, label, status = _event_to_run_step(compaction_event)
            _agent_store.append_run_event(
                request.session_id,
                run_id=run_id,
                type=step_type,
                label=label,
                status=status,
                payload=compaction_event.data,
            )
            yield format_sse(compaction_event)
    _agent_store.append_run_event(
        request.session_id,
        run_id=run_id,
        type="user",
        label="收到输入",
        status="done",
        payload={"content": request.message},
    )

    history_messages = []
    if request.history:
        for item in request.history:
            if not item.content:
                continue
            if item.role == "assistant":
                history_messages.append(AIMessage(content=item.content))
            else:
                history_messages.append(HumanMessage(content=item.content))
    else:
        stored_messages = _agent_store.list_messages(request.session_id, limit=24)
        for item in stored_messages:
            if not item.content or item.content == request.message:
                continue
            if item.role == "assistant":
                history_messages.append(AIMessage(content=item.content))
            elif item.role == "user":
                history_messages.append(HumanMessage(content=item.content))

    inputs = {
        "session_id": request.session_id,
        "agent_id": request.agent_id,
        "metadata": {**request.metadata, "run_id": run_id},
        "messages": [*history_messages, HumanMessage(content=request.message)],
    }
    config = build_thread_config(request.session_id)
    assistant_tokens: list[str] = []
    assistant_message_parts: list[dict[str, Any]] = []

    def append_text_part(content: str) -> None:
        if not content:
            return
        if assistant_message_parts and assistant_message_parts[-1].get("type") == "text":
            assistant_message_parts[-1]["content"] = (
                str(assistant_message_parts[-1].get("content", "")) + content
            )
            return
        assistant_message_parts.append(
            {"id": f"text-{uuid4().hex}", "type": "text", "content": content}
        )

    def upsert_tool_part(tool: dict[str, Any]) -> None:
        tool_id = str(tool.get("id") or tool.get("tool_call_id") or uuid4().hex)
        normalized = {
            "id": tool_id,
            "type": "tool",
            "tool": {
                "id": tool_id,
                "name": str(tool.get("name") or tool.get("tool") or "tool"),
                "status": str(tool.get("status") or "running"),
                "summary": str(tool.get("summary") or ""),
            },
        }
        for index, part in enumerate(assistant_message_parts):
            if part.get("type") == "tool" and (part.get("tool") or {}).get("id") == tool_id:
                existing_tool = dict(part.get("tool") or {})
                assistant_message_parts[index] = {
                    **part,
                    "tool": {**existing_tool, **normalized["tool"]},
                }
                return
        assistant_message_parts.append(normalized)

    try:
        async for part in graph.astream(
            inputs,
            config=config,
            stream_mode=["messages", "updates", "custom"],
        ):
            event = map_stream_part(part)
            if event is None:
                continue
            if event.type == "token":
                token = str(event.data.get("content", ""))
                assistant_tokens.append(token)
                append_text_part(token)
            elif event.type in {
                "tool_start",
                "tool_end",
                "node_end",
                "skill",
                "pact",
                "delegate",
                "compaction",
                "approval_pending",
                "approval_resolved",
                "subagent_start",
                "subagent_end",
            }:
                step_type, label, status = _event_to_run_step(event)
                _agent_store.append_run_event(
                    request.session_id,
                    run_id=run_id,
                    type=step_type,
                    label=label,
                    status=status,
                    payload=event.data,
                )
            if event.type == "tool_start":
                tool_call_id = str(event.data.get("tool_call_id") or event.data.get("run_id") or "tool")
                args = event.data.get("args") if isinstance(event.data.get("args"), dict) else {}
                upsert_tool_part(
                    {
                        "id": tool_call_id,
                        "tool": event.data.get("tool", "tool"),
                        "status": "running",
                        "summary": json.dumps(args, ensure_ascii=False) if args else "正在运行…",
                    }
                )
                _agent_store.upsert_tool_call(
                    request.session_id,
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    name=str(event.data.get("tool", "tool")),
                    status="running",
                    args=args,
                )
            elif event.type == "tool_end":
                tool_call_id = str(event.data.get("tool_call_id") or event.data.get("run_id") or "tool")
                status = "error" if str(event.data.get("status", "ok")) == "error" else "done"
                result = str(event.data.get("content") or event.data.get("output") or "")
                upsert_tool_part(
                    {
                        "id": tool_call_id,
                        "tool": event.data.get("tool", "tool"),
                        "status": status,
                        "summary": result,
                    }
                )
                _agent_store.upsert_tool_call(
                    request.session_id,
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    name=str(event.data.get("tool", "tool")),
                    status=status,
                    result=result,
                )
            yield format_sse(event)
        assistant_content = "".join(assistant_tokens)
        if assistant_content:
            _agent_store.append_message(
                request.session_id,
                role="assistant",
                content=assistant_content,
                metadata={
                    "source": "chat_stream",
                    "run_id": run_id,
                    "parts": assistant_message_parts,
                },
            )
        memory_store.append_session_event(
            request.session_id,
            {"role": "assistant", "status": "done", "content": assistant_content},
        )
        final_event = done_event()
        step_type, label, status = _event_to_run_step(final_event)
        _agent_store.append_run_event(
            request.session_id,
            run_id=run_id,
            type=step_type,
            label=label,
            status=status,
            payload=final_event.data,
        )
        yield format_sse(final_event)
    except Exception as exc:  # noqa: BLE001 - API streams errors as client-visible SSE.
        event = error_event(exc)
        step_type, label, status = _event_to_run_step(event)
        _agent_store.append_run_event(
            request.session_id,
            run_id=run_id,
            type=step_type,
            label=label,
            status=status,
            payload=event.data,
        )
        yield format_sse(event)
        final_event = done_event()
        yield format_sse(final_event)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatStreamRequest) -> StreamingResponse:
    return StreamingResponse(
        _stream_chat(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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
        return {"path": catalog.normalize_relative_path(skill_path), "content": catalog.read_skill(skill_path)}
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

    approved = _agent_store.resolve_approval_request(approval_id, status="approved")
    if approved is None:
        raise HTTPException(status_code=404, detail="Approval request not found")

    run_id = str(approval["run_id"])
    session_id = str(approval["session_id"])
    _agent_store.append_run_event(
        session_id,
        run_id=run_id,
        type="approval",
        label=f"审批通过：{approval['tool_name']}",
        status="done",
        payload={"approval": approved},
    )

    try:
        if approval["tool_name"] == "delegate_task":
            args = approval.get("args") or {}
            _agent_store.append_run_event(
                session_id,
                run_id=run_id,
                type="subagent",
                label=f"子 Agent {args.get('target_agent', 'researcher')} 启动",
                status="running",
                payload={"approval": approval, "target_agent": args.get("target_agent", "researcher")},
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
async def health() -> dict[str, str]:
    return {"status": "ok"}


def app_root() -> Path:
    return DATA_ROOT.parents[1]
