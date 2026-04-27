from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
    latest_run: dict[str, Any] | None = None
    active_run: dict[str, Any] | None = None
    runs: list[dict[str, Any]] = Field(default_factory=list)
    context_pact: dict[str, Any] = Field(default_factory=dict)
    skill_proposals: list[dict[str, Any]] = Field(default_factory=list)
    memory_proposals: list[dict[str, Any]] = Field(default_factory=list)
    compaction_runs: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[dict[str, Any]] = Field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = Field(default_factory=list)


class ChatHistoryMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(default="")


class ChatStreamRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    agent_id: str = Field(default="default")
    metadata: dict[str, Any] = Field(default_factory=dict)
    history: list[ChatHistoryMessage] = Field(default_factory=list)
    reset_thread: bool = Field(default=False)


class RunCreateRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    agent_id: str = Field(default="default")
    metadata: dict[str, Any] = Field(default_factory=dict)
    history: list[ChatHistoryMessage] = Field(default_factory=list)
    reset_thread: bool = Field(default=False)


class RunCreateResponse(BaseModel):
    run_id: str
    status: str


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


class StopSessionRequest(BaseModel):
    run_id: str | None = None
    reason: str = Field(default="用户停止了本次运行")
