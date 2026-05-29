"""Small mailbox facade over agent_team_messages."""

from __future__ import annotations

from typing import Any


class TeamMailbox:
    def __init__(self, store: Any) -> None:
        self.store = store

    def post(
        self,
        *,
        team_id: str,
        content: str,
        from_member_id: str = "",
        to_member_id: str = "",
        task_id: str = "",
        kind: str = "note",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.store.agent_team_messages.create(
            team_id=team_id,
            content=content,
            from_member_id=from_member_id,
            to_member_id=to_member_id,
            task_id=task_id,
            kind=kind,
            metadata=metadata,
        )
