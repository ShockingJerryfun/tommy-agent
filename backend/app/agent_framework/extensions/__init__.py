"""Extensions — pluggable hooks and MCP tool providers.

This package is the single boundary for runtime extensions:

- :class:`HookRegistry` — phased hook registry with deterministic
  ordering, per-hook timeout, and an explicit failure policy. The same
  registry powers built-in hooks (memory flush before compact, stale
  approval cleanup, checkpoint pruning after a run) and any third-party
  hook installed at boot.
- :class:`MCPToolProvider` — adapter that turns MCP servers into
  ``langchain_core`` tools so they flow through the unified tool
  runtime, registry, and permission policy. The default registry can
  be queried for the set of currently available providers.

Public surface is intentionally narrow: the registry, the phase enum,
the hook context dataclass, the built-in hook constructors, and the
MCP provider primitives.
"""

from __future__ import annotations

from .builtins import (
    BuiltinHookSet,
    install_builtin_hooks,
    make_checkpoint_prune_hook,
    make_memory_flush_hook,
    make_stale_approval_cleanup_hook,
)
from .context import HookContext, HookOutcome
from .mcp import (
    MCPServer,
    MCPToolProvider,
    MCPToolSpec,
    StaticMCPServer,
    mcp_tool_from_spec,
)
from .phases import HookPhase
from .registry import (
    HookFailurePolicy,
    HookRegistration,
    HookRegistry,
    default_hook_registry,
    reset_default_hook_registry,
)

__all__ = [
    "BuiltinHookSet",
    "HookContext",
    "HookFailurePolicy",
    "HookOutcome",
    "HookPhase",
    "HookRegistration",
    "HookRegistry",
    "MCPServer",
    "MCPToolProvider",
    "MCPToolSpec",
    "StaticMCPServer",
    "default_hook_registry",
    "install_builtin_hooks",
    "make_checkpoint_prune_hook",
    "make_memory_flush_hook",
    "make_stale_approval_cleanup_hook",
    "mcp_tool_from_spec",
    "reset_default_hook_registry",
]
