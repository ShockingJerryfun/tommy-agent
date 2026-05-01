from __future__ import annotations

from typing import Any


class KnowledgeStoreMixin:
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
            proposal_id,
            version_id=version_id,
            previous_content=previous_content,
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
            agent_id=agent_id,
            relative_path=relative_path,
            limit=limit,
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
        return self.context_pacts.upsert_context_pact(session_id, agent_id=agent_id, pact=pact)

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
            session_id=session_id,
            status=status,
            limit=limit,
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
            approval_id,
            status=status,
            result=result,
            error=error,
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
