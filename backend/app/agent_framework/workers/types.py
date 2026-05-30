"""DTOs for shared worker execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .context import ChildRunContext


@dataclass(frozen=True)
class WorkerTask:
    id: str
    role_id: str
    task: str
    reason: str
    parent_session_id: str
    parent_run_id: str
    agent_id: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)
    attempt_index: int = 0
    child_context: ChildRunContext | None = None
    approval_id: str = ""


@dataclass(frozen=True)
class WorkerResult:
    task_id: str
    subagent_id: str
    child_session_id: str
    role_id: str
    status: str
    final_response: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
