"""Subagent run persistence — parent/child linkage + best-of-N scoring."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._base import Connector, dumps, loads, utc_now


class SubagentRunRepo:
    SELECT_COLUMNS = (
        "id, parent_session_id, parent_run_id, child_session_id, child_run_id, "
        "role, task, status, score, attempt_index, final_response, "
        "metadata_json, created_at, updated_at, finished_at"
    )

    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def create(
        self,
        *,
        parent_session_id: str,
        parent_run_id: str,
        child_session_id: str,
        role: str,
        task: str,
        attempt_index: int = 0,
        metadata: dict[str, Any] | None = None,
        status: str = "queued",
        child_run_id: str = "",
    ) -> dict[str, Any]:
        run_id = f"sub-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO subagent_runs(
                    id, parent_session_id, parent_run_id, child_session_id,
                    child_run_id, role, task, status, score, attempt_index,
                    final_response, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?, '', ?, ?, ?)
                """,
                (
                    run_id,
                    parent_session_id,
                    parent_run_id,
                    child_session_id,
                    child_run_id,
                    role,
                    task,
                    status,
                    int(attempt_index),
                    dumps(metadata),
                    now,
                    now,
                ),
            )
        return self.get(run_id) or {}

    def update(
        self,
        subagent_id: str,
        *,
        status: str | None = None,
        score: float | None = None,
        final_response: str | None = None,
        metadata_patch: dict[str, Any] | None = None,
        child_run_id: str | None = None,
        finished: bool = False,
    ) -> dict[str, Any] | None:
        existing = self.get(subagent_id)
        if existing is None:
            return None
        merged_meta = dict(existing.get("metadata") or {})
        if metadata_patch:
            merged_meta.update(metadata_patch)
        new_status = status or existing["status"]
        new_score = float(score) if score is not None else float(existing.get("score") or 0.0)
        new_response = (
            final_response if final_response is not None else existing.get("final_response", "")
        )
        new_child_run = (
            child_run_id if child_run_id is not None else existing.get("child_run_id", "")
        )
        now = utc_now()
        finished_at = now if finished or new_status in {"completed", "failed", "stopped"} else None
        with self._connector.connect() as conn:
            conn.execute(
                """
                UPDATE subagent_runs
                SET status = ?, score = ?, final_response = ?, metadata_json = ?,
                    child_run_id = ?, updated_at = ?,
                    finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (
                    new_status,
                    new_score,
                    new_response,
                    dumps(merged_meta),
                    new_child_run,
                    now,
                    finished_at,
                    subagent_id,
                ),
            )
        return self.get(subagent_id)

    def get(self, subagent_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute(
                f"SELECT {self.SELECT_COLUMNS} FROM subagent_runs WHERE id = ?",
                (subagent_id,),
            ).fetchone()
        return _hydrate(row) if row is not None else None

    def list_for_session(
        self,
        parent_session_id: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM subagent_runs
                WHERE parent_session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (parent_session_id, int(limit)),
            ).fetchall()
        return [_hydrate(row) for row in rows]

    def list_for_run(
        self,
        *,
        parent_session_id: str,
        parent_run_id: str,
    ) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM subagent_runs
                WHERE parent_session_id = ? AND parent_run_id = ?
                ORDER BY attempt_index ASC, created_at ASC
                """,
                (parent_session_id, parent_run_id),
            ).fetchall()
        return [_hydrate(row) for row in rows]


def _hydrate(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "parent_session_id": row["parent_session_id"],
        "parent_run_id": row["parent_run_id"],
        "child_session_id": row["child_session_id"],
        "child_run_id": row["child_run_id"],
        "role": row["role"],
        "task": row["task"],
        "status": row["status"],
        "score": float(row["score"]),
        "attempt_index": row["attempt_index"],
        "final_response": row["final_response"],
        "metadata": loads(row["metadata_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "finished_at": row["finished_at"],
    }
