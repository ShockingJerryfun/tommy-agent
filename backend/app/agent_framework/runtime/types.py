from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RunCreatePayload:
    session_id: str
    message: str
    agent_id: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, str]] = field(default_factory=list)
    reset_thread: bool = False
