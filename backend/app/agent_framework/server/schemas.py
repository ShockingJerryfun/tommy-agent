from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from ..runtime import AttachmentRef


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
    pinned: bool = False
    archived: bool = False
    created_at: str
    updated_at: str


class SessionPatchRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    pinned: bool | None = None
    archived: bool | None = None

    @model_validator(mode="after")
    def require_one_field(self) -> SessionPatchRequest:
        if self.title is None and self.pinned is None and self.archived is None:
            raise ValueError("At least one of title, pinned, or archived is required")
        return self


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
    message: str = Field(default="")
    agent_id: str = Field(default="default")
    metadata: dict[str, Any] = Field(default_factory=dict)
    history: list[ChatHistoryMessage] = Field(default_factory=list)
    attachments: list[AttachmentRef] = Field(default_factory=list)
    reset_thread: bool = Field(default=False)
    idempotency_key: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def require_message_or_attachment(self) -> ChatStreamRequest:
        if not self.message.strip() and not self.attachments:
            raise ValueError("Message or attachment is required")
        return self


class RunCreateRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    message: str = Field(default="")
    agent_id: str = Field(default="default")
    metadata: dict[str, Any] = Field(default_factory=dict)
    history: list[ChatHistoryMessage] = Field(default_factory=list)
    attachments: list[AttachmentRef] = Field(default_factory=list)
    reset_thread: bool = Field(default=False)
    idempotency_key: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def require_message_or_attachment(self) -> RunCreateRequest:
        if not self.message.strip() and not self.attachments:
            raise ValueError("Message or attachment is required")
        return self


class MessageEditRequest(BaseModel):
    content: str = Field(..., min_length=1)


class RerunMessageRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=128)
    agent_id: str = Field(default="default")
    metadata: dict[str, Any] = Field(default_factory=dict)
    content: str | None = Field(default=None, min_length=1)


class RegenerateMessageRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=128)
    agent_id: str = Field(default="default")
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunCreateResponse(BaseModel):
    run_id: str
    status: str


class PromptItem(BaseModel):
    id: str
    owner_user: str = ""
    kind: str = Field(..., pattern="^(builtin|user)$")
    name: str
    body: str
    shortcut: str = ""
    created_at: str
    updated_at: str


class CreatePromptRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    body: str = Field(..., min_length=1, max_length=8000)
    shortcut: str = Field(default="", max_length=64, pattern="^[a-z0-9_-]*$")


class UpdatePromptRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    body: str | None = Field(default=None, min_length=1, max_length=8000)
    shortcut: str | None = Field(default=None, max_length=64, pattern="^[a-z0-9_-]*$")


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
