from __future__ import annotations

from typing import Any


class PromptStoreMixin:
    def list_prompts(self, *, owner_user: str = "") -> list[dict[str, Any]]:
        return self.prompts.list_prompts(owner_user=owner_user)

    def get_prompt(self, prompt_id: str) -> dict[str, Any] | None:
        return self.prompts.get_prompt(prompt_id)

    def create_prompt(
        self,
        *,
        owner_user: str,
        name: str,
        body: str,
        shortcut: str = "",
    ) -> dict[str, Any]:
        return self.prompts.create_prompt(
            owner_user=owner_user,
            name=name,
            body=body,
            shortcut=shortcut,
        )

    def update_prompt(
        self,
        prompt_id: str,
        *,
        name: str | None = None,
        body: str | None = None,
        shortcut: str | None = None,
    ) -> dict[str, Any] | None:
        return self.prompts.update_prompt(
            prompt_id,
            name=name,
            body=body,
            shortcut=shortcut,
        )

    def delete_prompt(self, prompt_id: str) -> bool:
        return self.prompts.delete_prompt(prompt_id)

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
            session_id=session_id,
            run_id=run_id,
            limit=limit,
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
