from __future__ import annotations

from typing import Any

from ..repos import StoredMessage


class ConversationStoreMixin:
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

    def update_session_metadata(
        self,
        session_id: str,
        *,
        title: str | None = None,
        pinned: bool | None = None,
        archived: bool | None = None,
    ) -> dict[str, Any] | None:
        return self.sessions.update_session_metadata(
            session_id,
            title=title,
            pinned=pinned,
            archived=archived,
        )

    def set_share_token(self, session_id: str, token: str | None) -> None:
        self.sessions.set_share_token(session_id, token)

    def get_session_by_share_token(self, token: str) -> dict[str, Any] | None:
        return self.sessions.get_session_by_share_token(token)

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
            session_id,
            role=role,
            content=content,
            metadata=metadata,
        )

    def get_message(self, message_id: str) -> StoredMessage | None:
        return self.messages.get_message(message_id)

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

    def delete_messages_after(self, session_id: str, position: int) -> int:
        return self.messages.delete_after(session_id, position)

    def reset_session_content(
        self,
        session_id: str,
        *,
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        self.messages.reset_session_content(session_id, messages=messages)

    def search_messages(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        return self.search.search_messages(query, limit=limit)
