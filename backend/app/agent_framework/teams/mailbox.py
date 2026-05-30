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

    def list_recent(self, team_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        return self.store.agent_team_messages.list_for_team(team_id, limit=limit)

    def bounded_section(self, team_id: str, *, limit: int = 10, max_chars: int = 1200) -> str:
        messages = self.list_recent(team_id, limit=limit)
        lines = ["Mailbox"]
        for message in messages:
            prefix = message.get("from_member_id") or "team"
            lines.append(f"- {prefix}: {message.get('content', '')}")
        text = "\n".join(lines)
        if len(text) <= max_chars:
            return text
        return text[: max(0, max_chars - 3)].rstrip() + "..."
