"""Typed result objects returned by :class:`ToolRuntime`.

These types replace the raw ``str`` contract used by ``ToolRegistry.invoke``
so that downstream code (LangGraph nodes, persistence, the model itself)
can reason about validation/permission/runtime errors in a structured way
and so that auto-spilled outputs carry an explicit reference back to their
``tool_artifacts`` row.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ToolErrorCode = Literal[
    "validation_error",
    "permission_denied",
    "approval_pending",
    "runtime_error",
    "timeout",
    "not_found",
    "unsupported",
]


@dataclass(frozen=True)
class ToolError:
    """Structured error surfaced to the model and persisted with the call."""

    code: ToolErrorCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}

    def to_message(self) -> str:
        return json.dumps(
            {"status": "error", "error": self.to_dict()},
            ensure_ascii=False,
            default=str,
        )


@dataclass(frozen=True)
class ArtifactRef:
    """Compact reference returned to the model when a body is auto-spilled."""

    artifact_id: str
    tool_call_id: str
    tool_name: str
    size_bytes: int
    sha256: str
    mime: str = "text/plain"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_message(self, *, preview: str = "") -> str:
        return json.dumps(
            {
                "status": "ok",
                "spilled": True,
                "artifact": self.to_dict(),
                "preview": preview,
                "note": (
                    "Output exceeded the inline budget and was stored as an "
                    "artifact. Reference it by id when you need the full body."
                ),
            },
            ensure_ascii=False,
            default=str,
        )


@dataclass
class ToolResult:
    """Normalized tool outcome returned by :class:`ToolRuntime.execute`.

    ``content`` is what the model receives back as the ``ToolMessage`` body.
    For successful small outputs this is the raw string. For successful
    large outputs it is the artifact reference JSON. For failures it is the
    serialised :class:`ToolError`.
    """

    name: str
    tool_call_id: str
    status: Literal["ok", "pending_approval", "error"]
    content: str
    error: ToolError | None = None
    artifact: ArtifactRef | None = None
    raw_size_bytes: int = 0
    spilled: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_step(self) -> dict[str, Any]:
        step: dict[str, Any] = {
            "node": "action",
            "tool": self.name,
            "tool_call_id": self.tool_call_id,
            "status": self.status,
        }
        if self.error is not None:
            step["error"] = self.error.to_dict()
        if self.artifact is not None:
            step["artifact_id"] = self.artifact.artifact_id
            step["spilled"] = True
        if self.metadata:
            step["metadata"] = dict(self.metadata)
        return step
