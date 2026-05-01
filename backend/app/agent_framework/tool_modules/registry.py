from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import BaseTool

from .basic import get_current_time
from .collaboration import context_pact_update, delegate_task, skill_propose
from .context import RUNTIME_TOOL_CONTEXT
from .filesystem import (
    list_local_directory,
    list_workspace,
    read_local_file,
    read_workspace_file,
    run_shell_command,
    write_local_file,
)
from .web import web_search


@dataclass(frozen=True)
class ToolRegistry:
    tools: tuple[BaseTool, ...]

    @property
    def by_name(self) -> dict[str, BaseTool]:
        return {tool_.name: tool_ for tool_ in self.tools}

    def schemas(self) -> list[BaseTool]:
        return list(self.tools)

    def invoke(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        context: dict[str, Any] | None = None,
    ) -> str:
        tool_ = self.by_name.get(name)
        if tool_ is None:
            raise KeyError(f"Unknown tool: {name}")
        token = RUNTIME_TOOL_CONTEXT.set(context or {})
        try:
            result = tool_.invoke(args or {})
        finally:
            RUNTIME_TOOL_CONTEXT.reset(token)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)


def create_default_registry() -> ToolRegistry:
    return ToolRegistry(
        tools=(
            get_current_time,
            web_search,
            read_workspace_file,
            list_workspace,
            read_local_file,
            list_local_directory,
            write_local_file,
            run_shell_command,
            skill_propose,
            context_pact_update,
            delegate_task,
        )
    )
