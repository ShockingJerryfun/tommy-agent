"""DTOs for Agent Teams."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TeamMemberSpec:
    role: str
    agent_definition_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
