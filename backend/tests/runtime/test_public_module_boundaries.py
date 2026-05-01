from __future__ import annotations


def test_domain_modules_expose_public_ports() -> None:
    from app.agent_framework.prompt_context import (
        ContextBuilder,
        merge_context_pact,
        messages_with_context,
    )
    from app.agent_framework.runtime import (
        AgentEvent,
        AttachmentStore,
        RunCreatePayload,
        RunManager,
        compact_transcript_records,
        format_sse,
    )
    from app.agent_framework.server import ChatStreamRequest, CreateSessionRequest
    from app.agent_framework.server import app as server_app_module
    from app.agent_framework.skills_forge import SkillCatalog
    from app.agent_framework.storage import LocalMemoryStore, PostgresAgentStore
    from app.agent_framework.subagents import HermesDelegateConfig, run_delegate_task
    from app.agent_framework.tool_runtime import ToolRegistry, create_default_registry

    assert server_app_module.app.title == "Tommy Agent Framework"
    assert ChatStreamRequest.__name__ == "ChatStreamRequest"
    assert CreateSessionRequest.__name__ == "CreateSessionRequest"
    assert AgentEvent.__name__ == "AgentEvent"
    assert format_sse.__name__ == "format_sse"
    assert AttachmentStore.__name__ == "AttachmentStore"
    assert compact_transcript_records.__name__ == "compact_transcript_records"
    assert PostgresAgentStore.__name__ == "PostgresAgentStore"
    assert LocalMemoryStore.__name__ == "LocalMemoryStore"
    assert RunManager.__name__ == "RunManager"
    assert ContextBuilder.__name__ == "ContextBuilder"
    assert merge_context_pact.__name__ == "merge_context_pact"
    assert messages_with_context.__name__ == "messages_with_context"
    assert SkillCatalog.__name__ == "SkillCatalog"
    assert run_delegate_task.__name__ == "run_delegate_task"
    assert HermesDelegateConfig.__name__ == "HermesDelegateConfig"
    assert RunCreatePayload.__name__ == "RunCreatePayload"
    assert ToolRegistry.__name__ == "ToolRegistry"
    assert create_default_registry.__name__ == "create_default_registry"
