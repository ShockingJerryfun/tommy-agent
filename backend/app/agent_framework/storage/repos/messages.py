"""Message repository."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._base import (
    Connector,
    StoredMessage,
    dumps,
    loads,
    refresh_session_summary,
    utc_now,
)


class MessageRepo:
    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> StoredMessage:
        now = utc_now()
        message_id = f"msg-{uuid4().hex}"
        with self._connector.connect() as conn:
            position = (
                conn.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM messages WHERE session_id = ?",
                    (session_id,),
                ).fetchone()[0]
                or 0
            )
            conn.execute(
                """
                INSERT INTO messages(
                    id, session_id, role, content, metadata_json, position, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, session_id, role, content, dumps(metadata), position, now),
            )
            refresh_session_summary(conn, session_id)
        return StoredMessage(
            id=message_id,
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata or {},
            position=position,
            created_at=now,
        )

    def update_message(
        self,
        message_id: str,
        *,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StoredMessage | None:
        updates: list[str] = []
        params: list[Any] = []
        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if metadata is not None:
            updates.append("metadata_json = ?")
            params.append(dumps(metadata))
        if not updates:
            return None

        with self._connector.connect() as conn:
            row = conn.execute(
                """
                SELECT id, session_id, role, content, metadata_json, position, created_at
                FROM messages
                WHERE id = ?
                """,
                (message_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                f"UPDATE messages SET {', '.join(updates)} WHERE id = ?",
                (*params, message_id),
            )
            refresh_session_summary(conn, row["session_id"])
            updated = conn.execute(
                """
                SELECT id, session_id, role, content, metadata_json, position, created_at
                FROM messages
                WHERE id = ?
                """,
                (message_id,),
            ).fetchone()
        if updated is None:
            return None
        return StoredMessage(
            id=updated["id"],
            session_id=updated["session_id"],
            role=updated["role"],
            content=updated["content"],
            metadata=loads(updated["metadata_json"]),
            position=updated["position"],
            created_at=updated["created_at"],
        )

    def list_messages(self, session_id: str, *, limit: int | None = None) -> list[StoredMessage]:
        sql = """
            SELECT id, session_id, role, content, metadata_json, position, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY position ASC
        """
        params: tuple[Any, ...] = (session_id,)
        if limit is not None:
            sql = """
                SELECT id, session_id, role, content, metadata_json, position, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY position DESC
                LIMIT ?
            """
            params = (session_id, limit)
        with self._connector.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        messages = [
            StoredMessage(
                id=row["id"],
                session_id=row["session_id"],
                role=row["role"],
                content=row["content"],
                metadata=loads(row["metadata_json"]),
                position=row["position"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
        return sorted(messages, key=lambda item: item.position)

    def reset_session_content(
        self,
        session_id: str,
        *,
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute("DELETE FROM tool_calls WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM run_events WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            for position, message in enumerate(messages or []):
                conn.execute(
                    """
                    INSERT INTO messages(
                        id, session_id, role, content, metadata_json, position, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"msg-{uuid4().hex}",
                        session_id,
                        message["role"],
                        message["content"],
                        dumps(message.get("metadata")),
                        position,
                        now,
                    ),
                )
            refresh_session_summary(conn, session_id)
