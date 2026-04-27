"""Hook execution context and outcome dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .phases import HookPhase


@dataclass
class HookContext:
    """Payload threaded through every hook invocation.

    The context is mutable inside a single dispatch round so a hook
    can stash advisory data for downstream hooks under ``data``. The
    registry never serializes or persists this context.
    """

    phase: HookPhase
    session_id: str = ""
    run_id: str = ""
    agent_id: str = "default"
    payload: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)


@dataclass(frozen=True)
class HookOutcome:
    """Result of one hook invocation."""

    name: str
    phase: HookPhase
    status: str  # 'ok' | 'error' | 'timeout' | 'skipped'
    duration_ms: float
    error: str | None = None
