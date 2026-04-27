"""Session repository."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._base import Connector, dumps, loads, utc_now


class SessionRepo:
    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def create_session(
        self,
        *,
        session_id: str | None = None,
        agent_id: str = "default",
        title: str = "新对话",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        sid = session_id or f"web-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions(
                    id, agent_id, title, preview, summary,
                    metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, '', '', ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    agent_id = excluded.agent_id,
                    updated_at = sessions.updated_at,
                    deleted_at = NULL
                """,
                (sid, agent_id, title, dumps(metadata), now, now),
            )
        return sid

    def ensure_session(self, session_id: str, *, agent_id: str = "default") -> None:
        self.create_session(session_id=session_id, agent_id=agent_id)

    def list_sessions(self, *, agent_id: str = "default") -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, agent_id, title, preview, summary, metadata_json, created_at, updated_at
                FROM sessions
                WHERE agent_id = ? AND deleted_at IS NULL
                ORDER BY updated_at DESC
                """,
                (agent_id,),
            ).fetchall()
        return [dict(row) | {"metadata": loads(row["metadata_json"])} for row in rows]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute(
                """
                SELECT id, agent_id, title, preview, summary, metadata_json, created_at, updated_at
                FROM sessions
                WHERE id = ? AND deleted_at IS NULL
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(row) | {"metadata": loads(row["metadata_json"])}

    def delete_session(self, session_id: str) -> None:
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                "UPDATE sessions SET deleted_at = ?, updated_at = ? WHERE id = ?",
                (now, now, session_id),
            )

    def set_session_summary(self, session_id: str, summary: str) -> None:
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                "UPDATE sessions SET summary = ?, updated_at = ? WHERE id = ?",
                (summary, now, session_id),
            )
