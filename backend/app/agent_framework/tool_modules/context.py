from __future__ import annotations

from contextvars import ContextVar
from typing import Any

RUNTIME_TOOL_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "runtime_tool_context",
    default=None,
)


def runtime_context() -> dict[str, Any]:
    return dict(RUNTIME_TOOL_CONTEXT.get() or {})


def require_approval(tool_name: str) -> None:
    if not runtime_context().get("approval_granted"):
        raise PermissionError(f"{tool_name} requires explicit user approval before execution.")
