"""S4 tool runtime — typed pipeline around ``ToolRegistry``.

Pipeline: validate → permission → run → persist → artifact (auto-spill).

Public surface:

- :class:`ToolError`, :class:`ToolResult`, :class:`ArtifactRef` — typed
  return values used by the new executor.
- :class:`ToolRuntime` — the orchestrator. ``ToolRuntime.execute`` returns
  a :class:`ToolResult`; large outputs are spilled to ``tool_artifacts``
  and the model receives a compact reference JSON.
- :func:`load_permission_policy` / :class:`PermissionPolicy` — yaml-driven
  policy used by tool execution and approval handling.
"""

from __future__ import annotations

from .catalog import (
    RUNTIME_TOOL_CONTEXT,
    ContextPactUpdateArgs,
    DelegateTaskArgs,
    ListLocalDirectoryArgs,
    ListWorkspaceArgs,
    ReadLocalFileArgs,
    ReadWorkspaceFileArgs,
    RunShellCommandArgs,
    SkillProposeArgs,
    ToolRegistry,
    WebSearchArgs,
    WriteLocalFileArgs,
    context_pact_update,
    create_default_registry,
    delegate_task,
    get_current_time,
    list_local_directory,
    list_workspace,
    read_local_file,
    read_workspace_file,
    run_shell_command,
    skill_propose,
    web_search,
    write_local_file,
)
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
    "ContextPactUpdateArgs",
    "DelegateTaskArgs",
    "ListLocalDirectoryArgs",
    "ListWorkspaceArgs",
    "PermissionDecision",
    "PermissionPolicy",
    "RUNTIME_TOOL_CONTEXT",
    "ReadLocalFileArgs",
    "ReadWorkspaceFileArgs",
    "RunShellCommandArgs",
    "SkillProposeArgs",
    "ToolError",
    "ToolErrorCode",
    "ToolResult",
    "ToolRuntime",
    "ToolRegistry",
    "WebSearchArgs",
    "WriteLocalFileArgs",
    "context_pact_update",
    "create_default_registry",
    "default_permission_policy",
    "delegate_task",
    "get_current_time",
    "list_local_directory",
    "list_workspace",
    "load_permission_policy",
    "make_tool_runtime",
    "read_local_file",
    "read_workspace_file",
    "run_shell_command",
    "skill_propose",
    "web_search",
    "write_local_file",
]
