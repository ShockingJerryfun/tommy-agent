"""Compaction-run repository."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._base import Connector, dumps, loads, utc_now


class CompactionRepo:
    def __init__(self, connector: Connector) -> None:
        self._connector = connector

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
        compaction_id = f"compact-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO compaction_runs(
                    id, session_id, run_id, summary, message_count,
                    kept_messages, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    compaction_id,
                    session_id,
                    run_id,
                    summary,
                    message_count,
                    kept_messages,
                    dumps(metadata),
                    now,
                ),
            )
        return {
            "id": compaction_id,
            "session_id": session_id,
            "run_id": run_id,
            "summary": summary,
            "message_count": message_count,
            "kept_messages": kept_messages,
            "metadata": metadata or {},
            "created_at": now,
        }

    def list_compaction_runs(self, session_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM compaction_runs
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [dict(row) | {"metadata": loads(row["metadata_json"])} for row in rows]
