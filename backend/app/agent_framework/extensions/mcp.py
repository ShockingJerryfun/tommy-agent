"""MCP servers as tool providers (same registry contract as native tools).

Tommy treats Model Context Protocol servers as another *tool provider*
behind the unified tool runtime. Every MCP tool is wrapped into a
``langchain_core.tools.StructuredTool`` so it lives alongside native
Python tools in the :class:`ToolRegistry` and is governed by the same
:class:`PermissionPolicy` and ``ToolRuntime`` pipeline.

This module ships a small protocol (:class:`MCPServer`) and a static
test stub (:class:`StaticMCPServer`) so the integration is testable
without spinning up a real MCP transport. Boot wiring (stdio, sse,
websocket) is the responsibility of higher-level glue and is out of
scope for the framework core.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, create_model

from ..tool_runtime import ToolRegistry

# --------------------------------------------------------------------- protocol


class MCPServer(Protocol):
    """Minimal protocol the registry needs from any MCP server.

    Real implementations (stdio/SSE/WebSocket) wrap the protocol around
    a transport. Tests use :class:`StaticMCPServer`.
    """

    name: str

    def list_tools(self) -> list[MCPToolSpec]: ...

    def call_tool(self, *, tool_name: str, arguments: dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class MCPToolSpec:
    """Declarative spec for a single MCP-provided tool."""

    name: str  # MCP's local tool name
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------- static stub


@dataclass
class StaticMCPServer:
    """In-memory MCP server used for tests and scripted demos."""

    name: str
    tools: list[MCPToolSpec] = field(default_factory=list)
    handlers: dict[str, Callable[..., Any]] = field(default_factory=dict)

    def list_tools(self) -> list[MCPToolSpec]:
        return list(self.tools)

    def call_tool(self, *, tool_name: str, arguments: dict[str, Any]) -> Any:
        handler = self.handlers.get(tool_name)
        if handler is None:
            raise KeyError(f"unknown MCP tool: {tool_name}")
        return handler(**arguments)


# --------------------------------------------------------------------- conversion


_PYDANTIC_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _schema_to_args_model(spec: MCPToolSpec, server_name: str) -> type[BaseModel]:
    """Convert an MCP JSON-Schema-ish input spec to a Pydantic model.

    We support flat shape (``type``: object, ``properties``: {...},
    ``required``: [...]) — the dominant MCP shape. Unknown types fall
    back to ``str`` to keep the conversion best-effort.
    """

    schema = spec.input_schema or {}
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    fields: dict[str, tuple[type, Any]] = {}
    for key, prop in properties.items():
        py_type = _PYDANTIC_TYPE_MAP.get(str(prop.get("type") or "string"), str)
        default = ... if key in required else prop.get("default")
        description = str(prop.get("description") or "")
        fields[key] = (py_type, Field(default, description=description))
    if not fields:
        fields["payload"] = (str, Field(default="", description="raw payload"))
    model = create_model(
        f"MCPArgs_{server_name}_{spec.name}",
        __config__=ConfigDict(extra="allow"),
        **fields,
    )
    return model


def mcp_tool_from_spec(server: MCPServer, spec: MCPToolSpec) -> StructuredTool:
    """Wrap an MCP tool spec as a ``StructuredTool`` for the registry."""

    args_model = _schema_to_args_model(spec, server.name)

    def _invoke(**kwargs: Any) -> str:
        result = server.call_tool(tool_name=spec.name, arguments=kwargs)
        if isinstance(result, str):
            return result
        return str(result)

    qualified_name = f"mcp.{server.name}.{spec.name}"
    return StructuredTool.from_function(
        func=_invoke,
        name=qualified_name,
        description=spec.description or qualified_name,
        args_schema=args_model,
    )


# --------------------------------------------------------------------- provider


class MCPToolProvider:
    """Aggregates one or more MCP servers and exposes them as a registry."""

    def __init__(self, servers: Iterable[MCPServer] | None = None) -> None:
        self._servers: list[MCPServer] = list(servers or [])

    def add(self, server: MCPServer) -> None:
        self._servers.append(server)

    def remove(self, name: str) -> int:
        before = len(self._servers)
        self._servers = [s for s in self._servers if s.name != name]
        return before - len(self._servers)

    @property
    def servers(self) -> list[MCPServer]:
        return list(self._servers)

    def list_tools(self) -> list[StructuredTool]:
        tools: list[StructuredTool] = []
        for server in self._servers:
            for spec in server.list_tools():
                tools.append(mcp_tool_from_spec(server, spec))
        return tools

    def to_registry(self, *, base: ToolRegistry | None = None) -> ToolRegistry:
        """Build a fresh :class:`ToolRegistry` containing native + MCP tools."""

        existing: list[Any] = list(base.tools) if base else []
        merged = existing + list(self.list_tools())
        return ToolRegistry(tools=tuple(merged))
