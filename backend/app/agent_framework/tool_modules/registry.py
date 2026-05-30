from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import BaseTool

from .basic import get_current_time
from .chatgpt_web import (
    chatgpt_download_latest_images,
    chatgpt_extract_latest_text,
    chatgpt_new_chat,
    chatgpt_open,
    chatgpt_save_artifacts,
    chatgpt_send_message,
    chatgpt_wait_until_done,
)
from .collaboration import (
    cancel_agent_team_run,
    cancel_agent_workflow_run,
    context_pact_update,
    create_agent_team,
    delegate_task,
    get_agent_team_status,
    get_agent_workflow_status,
    rerun_failed_workflow_phase,
    run_agent_team,
    run_agent_workflow,
    skill_propose,
)
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
from .xhs_content_ops import (
    build_chatgpt_xhs_prompt,
    check_xhs_content_risk,
    create_xhs_content_job,
    validate_xhs_note_json,
)
from .xhs_web import (
    xhs_fill_body,
    xhs_fill_hashtags,
    xhs_fill_title,
    xhs_open_creator,
    xhs_start_note,
    xhs_stop_before_publish,
    xhs_take_preview_screenshot,
    xhs_upload_images,
)


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
            create_agent_team,
            run_agent_team,
            get_agent_team_status,
            cancel_agent_team_run,
            run_agent_workflow,
            get_agent_workflow_status,
            cancel_agent_workflow_run,
            rerun_failed_workflow_phase,
            create_xhs_content_job,
            build_chatgpt_xhs_prompt,
            validate_xhs_note_json,
            check_xhs_content_risk,
            chatgpt_open,
            chatgpt_new_chat,
            chatgpt_send_message,
            chatgpt_wait_until_done,
            chatgpt_extract_latest_text,
            chatgpt_download_latest_images,
            chatgpt_save_artifacts,
            xhs_open_creator,
            xhs_start_note,
            xhs_upload_images,
            xhs_fill_title,
            xhs_fill_body,
            xhs_fill_hashtags,
            xhs_take_preview_screenshot,
            xhs_stop_before_publish,
        )
    )
