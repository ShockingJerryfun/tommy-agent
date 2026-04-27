"""``PostgresAgentStore`` — thin facade over the repository modules.

The previous ~1.8k-line monolith has been carved into focused repos under
``storage/repos/``. This module composes those repos and exposes the same
public surface that routes, runs, skills, tests, and the run manager
already depend on, so the carve is behavior-preserving.

New code should depend on the individual ``*Repo`` classes (or, where
appropriate, the typed ``storage.interfaces`` Protocols) rather than this
facade. This file will continue to shrink across S1+.
"""

from __future__ import annotations

from typing import Any

from .settings import load_settings
from .storage.repos import (
    ApprovalRepo,
    CompactionRepo,
    Connector,
    ConsolidationRunRepo,
    ContextPactRepo,
    EventRepo,
    MemoryInjectionRepo,
    MemoryRepo,
    MessageRepo,
    PromptSnapshotRepo,
    RunControlRepo,
    RunMetricsRepo,
    RunRepo,
    SessionRepo,
    SkillCatalogRepo,
    SkillForgeRunRepo,
    SkillRepo,
    StoredMessage,
    SubagentRunRepo,
    ToolArtifactRepo,
    ToolCallRepo,
    ensure_schema,
    reset_for_tests,
    utc_now,
)

__all__ = ["PostgresAgentStore", "StoredMessage", "utc_now"]


class PostgresAgentStore:
    """Composite store that delegates to focused repository modules."""

    backend = "postgres"

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or load_settings().postgres_dsn
        self._connector = Connector(self.dsn)
        self.sessions = SessionRepo(self._connector)
        self.messages = MessageRepo(self._connector)
        self.runs = RunRepo(self._connector)
        self.run_controls = RunControlRepo(self._connector)
        self.events = EventRepo(self._connector)
        self.tool_calls = ToolCallRepo(self._connector)
        self.tool_artifacts = ToolArtifactRepo(self._connector)
        self.approvals = ApprovalRepo(self._connector)
        self.memories = MemoryRepo(self._connector)
        self.skills = SkillRepo(self._connector)
        self.skill_catalog = SkillCatalogRepo(self._connector)
        self.skill_forge_runs = SkillForgeRunRepo(self._connector)
        self.subagent_runs = SubagentRunRepo(self._connector)
        self.run_metrics = RunMetricsRepo(self._connector)
        self.context_pacts = ContextPactRepo(self._connector)
        self.compactions = CompactionRepo(self._connector)
        self.prompt_snapshots = PromptSnapshotRepo(self._connector)
        self.memory_injections = MemoryInjectionRepo(self._connector)
        self.consolidation_runs = ConsolidationRunRepo(self._connector)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        ensure_schema(self._connector)

    def reset_for_tests(self) -> None:
        reset_for_tests(self._connector)

    def create_session(
        self,
        *,
        session_id: str | None = None,
        agent_id: str = "default",
        title: str = "新对话",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return self.sessions.create_session(
            session_id=session_id,
            agent_id=agent_id,
            title=title,
            metadata=metadata,
        )

    def ensure_session(self, session_id: str, *, agent_id: str = "default") -> None:
        self.sessions.ensure_session(session_id, agent_id=agent_id)

    def list_sessions(self, *, agent_id: str = "default") -> list[dict[str, Any]]:
        return self.sessions.list_sessions(agent_id=agent_id)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self.sessions.get_session(session_id)

    def delete_session(self, session_id: str) -> None:
        self.sessions.delete_session(session_id)

    def set_session_summary(self, session_id: str, summary: str) -> None:
        self.sessions.set_session_summary(session_id, summary)

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> StoredMessage:
        return self.messages.append_message(
            session_id, role=role, content=content, metadata=metadata
        )

    def update_message(
        self,
        message_id: str,
        *,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StoredMessage | None:
        return self.messages.update_message(message_id, content=content, metadata=metadata)

    def list_messages(self, session_id: str, *, limit: int | None = None) -> list[StoredMessage]:
        return self.messages.list_messages(session_id, limit=limit)

    def reset_session_content(
        self,
        session_id: str,
        *,
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        self.messages.reset_session_content(session_id, messages=messages)

    def append_run_event(
        self,
        session_id: str,
        *,
        run_id: str,
        type: str,
        label: str,
        status: str = "done",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.events.append_run_event(
            session_id,
            run_id=run_id,
            type=type,
            label=label,
            status=status,
            payload=payload,
        )

    def list_run_events(self, session_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        return self.events.list_run_events(session_id, limit=limit)

    def list_run_events_after(
        self,
        run_id: str,
        *,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.events.list_run_events_after(
            run_id, after_sequence=after_sequence, limit=limit
        )

    def create_run(
        self,
        *,
        session_id: str,
        agent_id: str = "default",
        input: str,
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
        status: str = "queued",
    ) -> dict[str, Any]:
        return self.runs.create_run(
            session_id=session_id,
            agent_id=agent_id,
            input=input,
            metadata=metadata,
            run_id=run_id,
            status=status,
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.runs.get_run(run_id)

    def update_run_status(self, run_id: str, **updates: Any) -> dict[str, Any] | None:
        return self.runs.update_run_status(run_id, **updates)

    def request_run_cancel(self, run_id: str) -> dict[str, Any] | None:
        return self.runs.request_run_cancel(run_id)

    def is_run_cancel_requested(self, run_id: str) -> bool:
        return self.runs.is_run_cancel_requested(run_id)

    def list_runs(self, session_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        return self.runs.list_runs(session_id, limit=limit)

    def get_latest_run(self, session_id: str) -> dict[str, Any] | None:
        return self.runs.get_latest_run(session_id)

    def get_active_run(self, session_id: str) -> dict[str, Any] | None:
        return self.runs.get_active_run(session_id)

    def list_active_runs(
        self,
        *,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.runs.list_active_runs(session_id=session_id, limit=limit)

    def list_inflight_runs(
        self,
        *,
        session_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        return self.runs.list_inflight_runs(session_id=session_id, limit=limit)

    def finalize_run_as_interrupted(
        self,
        run_id: str,
        *,
        reason: str = "服务进程重启或连接断开后，运行已中断。",
    ) -> dict[str, Any] | None:
        return self.runs.finalize_run_as_interrupted(run_id, reason=reason)

    def start_run(self, session_id: str, *, run_id: str) -> dict[str, Any]:
        return self.run_controls.start_run(session_id, run_id=run_id)

    def request_run_stop(
        self,
        session_id: str,
        *,
        run_id: str | None = None,
        reason: str = "Stopped by user",
    ) -> list[dict[str, Any]]:
        return self.run_controls.request_run_stop(session_id, run_id=run_id, reason=reason)

    def run_stop_requested(self, *, session_id: str, run_id: str) -> bool:
        return self.run_controls.run_stop_requested(session_id=session_id, run_id=run_id)

    def finish_run(
        self,
        session_id: str,
        *,
        run_id: str,
        status: str,
        reason: str = "",
    ) -> dict[str, Any] | None:
        return self.run_controls.finish_run(
            session_id, run_id=run_id, status=status, reason=reason
        )

    def upsert_tool_call(
        self,
        session_id: str,
        *,
        run_id: str,
        tool_call_id: str,
        name: str,
        status: str,
        args: dict[str, Any] | None = None,
        result: str | None = None,
    ) -> None:
        self.tool_calls.upsert_tool_call(
            session_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            name=name,
            status=status,
            args=args,
            result=result,
        )

    def list_tool_calls(self, session_id: str) -> list[dict[str, Any]]:
        return self.tool_calls.list_tool_calls(session_id)

    def create_skill_proposal(
        self,
        *,
        agent_id: str,
        name: str,
        relative_path: str,
        action: str,
        rationale: str,
        content: str,
        risks: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "proposed",
    ) -> dict[str, Any]:
        return self.skills.create_skill_proposal(
            agent_id=agent_id,
            name=name,
            relative_path=relative_path,
            action=action,
            rationale=rationale,
            content=content,
            risks=risks,
            metadata=metadata,
            status=status,
        )

    def get_skill_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        return self.skills.get_skill_proposal(proposal_id)

    def list_skill_proposals(
        self,
        *,
        agent_id: str = "default",
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.skills.list_skill_proposals(agent_id=agent_id, status=status, limit=limit)

    def apply_skill_proposal(
        self,
        proposal_id: str,
        *,
        version_id: str,
        previous_content: str,
    ) -> dict[str, Any] | None:
        return self.skills.apply_skill_proposal(
            proposal_id, version_id=version_id, previous_content=previous_content
        )

    def reject_skill_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        return self.skills.reject_skill_proposal(proposal_id)

    def list_skill_versions(
        self,
        *,
        agent_id: str = "default",
        relative_path: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return self.skills.list_skill_versions(
            agent_id=agent_id, relative_path=relative_path, limit=limit
        )

    def get_context_pact(self, session_id: str, *, agent_id: str = "default") -> dict[str, Any]:
        return self.context_pacts.get_context_pact(session_id, agent_id=agent_id)

    def upsert_context_pact(
        self,
        session_id: str,
        *,
        agent_id: str = "default",
        pact: dict[str, Any],
    ) -> dict[str, Any]:
        return self.context_pacts.upsert_context_pact(
            session_id, agent_id=agent_id, pact=pact
        )

    def append_compaction_run(
        self,
        session_id: str,
        *,
        run_id: str | None,
        summary: str,
        message_count: int,
        kept_messages: int,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.compactions.append_compaction_run(
            session_id,
            run_id=run_id,
            summary=summary,
            message_count=message_count,
            kept_messages=kept_messages,
            metadata=metadata,
        )

    def list_compaction_runs(self, session_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        return self.compactions.list_compaction_runs(session_id, limit=limit)

    def create_approval_request(
        self,
        *,
        session_id: str,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        args: dict[str, Any],
        risk_level: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.approvals.create_approval_request(
            session_id=session_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            args=args,
            risk_level=risk_level,
            summary=summary,
            metadata=metadata,
        )

    def get_approval_request(self, approval_id: str) -> dict[str, Any] | None:
        return self.approvals.get_approval_request(approval_id)

    def list_approval_requests(
        self,
        *,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.approvals.list_approval_requests(
            session_id=session_id, status=status, limit=limit
        )

    def resolve_approval_request(
        self,
        approval_id: str,
        *,
        status: str,
        result: str = "",
        error: str = "",
    ) -> dict[str, Any] | None:
        return self.approvals.resolve_approval_request(
            approval_id, status=status, result=result, error=error
        )

    def create_memory(
        self,
        *,
        agent_id: str,
        content: str,
        status: str = "proposed",
        source_session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        importance: float | None = None,
    ) -> dict[str, Any]:
        return self.memories.create_memory(
            agent_id=agent_id,
            content=content,
            status=status,
            source_session_id=source_session_id,
            metadata=metadata,
            importance=importance,
        )

    def confirm_memory(self, memory_id: str) -> dict[str, Any] | None:
        return self.memories.confirm_memory(memory_id)

    def list_memories(
        self,
        *,
        agent_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.memories.list_memories(agent_id=agent_id, status=status, limit=limit)

    def search_memories(
        self,
        *,
        agent_id: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        return self.memories.search_memories(agent_id=agent_id, query=query, limit=limit)

    def record_prompt_snapshot(
        self,
        *,
        session_id: str,
        agent_id: str,
        run_id: str | None,
        model: str = "",
        total_chars: int,
        section_count: int,
        truncated_count: int,
        dropped_count: int,
        content_sha256: str,
        sections: list[dict[str, Any]],
        budget: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        injections: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return self.prompt_snapshots.record_snapshot(
            session_id=session_id,
            agent_id=agent_id,
            run_id=run_id,
            model=model,
            total_chars=total_chars,
            section_count=section_count,
            truncated_count=truncated_count,
            dropped_count=dropped_count,
            content_sha256=content_sha256,
            sections=sections,
            budget=budget,
            metadata=metadata,
            injections=injections,
        )

    def list_prompt_snapshots(
        self,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return self.prompt_snapshots.list_snapshots(
            session_id=session_id, run_id=run_id, limit=limit
        )

    def get_prompt_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        return self.prompt_snapshots.get_snapshot(snapshot_id)

    def list_memory_injections_for_snapshot(
        self,
        snapshot_id: str,
    ) -> list[dict[str, Any]]:
        return self.memory_injections.list_for_snapshot(snapshot_id)

    def list_memory_injections_for_session(
        self,
        session_id: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.memory_injections.list_for_session(session_id, limit=limit)
