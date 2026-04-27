"""Tool artifact repository — the auto-spill store for large tool outputs."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from ._base import Connector, dumps, loads, utc_now


def make_artifact_id() -> str:
    return f"art-{uuid.uuid4().hex[:24]}"


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


class ToolArtifactRepo:
    """Persists tool outputs that exceed the inline budget."""

    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def create(
        self,
        *,
        session_id: str,
        run_id: str | None,
        tool_call_id: str,
        tool_name: str,
        body: str,
        kind: str = "tool_output",
        mime: str = "text/plain",
        metadata: dict[str, Any] | None = None,
        artifact_id: str | None = None,
    ) -> dict[str, Any]:
        artifact_id = artifact_id or make_artifact_id()
        digest = sha256_of(body)
        size_bytes = len(body.encode("utf-8", errors="replace"))
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_artifacts(
                    id, session_id, run_id, tool_call_id, tool_name,
                    kind, mime, size_bytes, sha256, body,
                    metadata_json, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(id) DO NOTHING
                """,
                (
                    artifact_id,
                    session_id,
                    run_id,
                    tool_call_id,
                    tool_name,
                    kind,
                    mime,
                    size_bytes,
                    digest,
                    body,
                    dumps(metadata),
                    now,
                ),
            )
        return {
            "id": artifact_id,
            "session_id": session_id,
            "run_id": run_id,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "kind": kind,
            "mime": mime,
            "size_bytes": size_bytes,
            "sha256": digest,
            "metadata": metadata or {},
            "created_at": now,
        }

    def get(self, artifact_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute(
                """
                SELECT id, session_id, run_id, tool_call_id, tool_name,
                       kind, mime, size_bytes, sha256, body,
                       metadata_json, created_at
                FROM tool_artifacts
                WHERE id = %s
                """,
                (artifact_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(row) | {"metadata": loads(row["metadata_json"])}

    def list_for_session(self, session_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, run_id, tool_call_id, tool_name,
                       kind, mime, size_bytes, sha256,
                       metadata_json, created_at
                FROM tool_artifacts
                WHERE session_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (session_id, limit),
            ).fetchall()
        return [dict(row) | {"metadata": loads(row["metadata_json"])} for row in rows]

    def list_for_tool_call(self, tool_call_id: str) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, run_id, tool_call_id, tool_name,
                       kind, mime, size_bytes, sha256,
                       metadata_json, created_at
                FROM tool_artifacts
                WHERE tool_call_id = %s
                ORDER BY created_at ASC
                """,
                (tool_call_id,),
            ).fetchall()
        return [dict(row) | {"metadata": loads(row["metadata_json"])} for row in rows]
