"""S4 tool runtime — typed pipeline around ``ToolRegistry``.

Pipeline: validate → permission → run → persist → artifact (auto-spill).

Public surface:

- :class:`ToolError`, :class:`ToolResult`, :class:`ArtifactRef` — typed
  return values used by the new executor.
- :class:`ToolRuntime` — the orchestrator. ``ToolRuntime.execute`` returns
  a :class:`ToolResult`; large outputs are spilled to ``tool_artifacts``
  and the model receives a compact reference JSON.
- :func:`load_permission_policy` / :class:`PermissionPolicy` — yaml-driven
  policy used by both the runtime and the legacy ``approvals`` module.
"""

from __future__ import annotations

from .executor import (
    ARTIFACT_SPILL_THRESHOLD,
    ToolRuntime,
    make_tool_runtime,
)
from .permissions import (
    PermissionDecision,
    PermissionPolicy,
    default_permission_policy,
    load_permission_policy,
)
from .result import (
    ArtifactRef,
    ToolError,
    ToolErrorCode,
    ToolResult,
)

__all__ = [
    "ARTIFACT_SPILL_THRESHOLD",
    "ArtifactRef",
    "PermissionDecision",
    "PermissionPolicy",
    "ToolError",
    "ToolErrorCode",
    "ToolResult",
    "ToolRuntime",
    "default_permission_policy",
    "load_permission_policy",
    "make_tool_runtime",
]
