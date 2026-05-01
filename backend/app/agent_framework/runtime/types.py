from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from typing_extensions import TypedDict


class AttachmentRef(TypedDict):
    id: str
    mime: str
    byte_size: int
    name: str


@dataclass(frozen=True)
class RunCreatePayload:
    session_id: str
    message: str
    agent_id: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, str]] = field(default_factory=list)
    attachments: list[AttachmentRef] = field(default_factory=list)
    reset_thread: bool = False
    idempotency_key: str | None = None
    skip_user_persist: bool = False
