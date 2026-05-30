"""Subagent run persistence — parent/child linkage + best-of-N scoring."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._base import Connector, dumps, loads, utc_now


class SubagentRunRepo:
    SELECT_COLUMNS = (
        "id, parent_session_id, parent_run_id, child_session_id, child_run_id, "
        "role, role_id, agent_definition_id, team_id, team_run_id, team_task_id, "
        "workflow_run_id, phase_run_id, workflow_phase_id, approval_id, task, status, "
        "score, attempt_index, final_response, error_type, error_message, "
        "metadata_json, created_at, started_at, updated_at, finished_at"
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
        role_id: str = "",
        agent_definition_id: str = "",
        team_id: str = "",
        team_run_id: str = "",
        team_task_id: str = "",
        workflow_run_id: str = "",
        phase_run_id: str = "",
        workflow_phase_id: str = "",
        approval_id: str = "",
    ) -> dict[str, Any]:
        run_id = f"sub-{uuid4().hex}"
        now = utc_now()
        effective_role_id = role_id or role
        effective_definition_id = agent_definition_id or effective_role_id
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO subagent_runs(
                    id, parent_session_id, parent_run_id, child_session_id,
                    child_run_id, role, role_id, agent_definition_id, team_id, team_run_id,
                    team_task_id, workflow_run_id, phase_run_id, workflow_phase_id,
                    approval_id, task, status, score, attempt_index, final_response,
                    metadata_json, created_at, started_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    parent_session_id,
                    parent_run_id,
                    child_session_id,
                    child_run_id,
                    role,
                    effective_role_id,
                    effective_definition_id,
                    team_id,
                    team_run_id,
                    team_task_id,
                    workflow_run_id,
                    phase_run_id,
                    workflow_phase_id,
                    approval_id,
                    task,
                    status,
                    0.0,
                    int(attempt_index),
                    "",
                    dumps(metadata),
                    now,
                    now if status == "running" else None,
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
        error_type: str | None = None,
        error_message: str | None = None,
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
        new_error_type = error_type if error_type is not None else existing.get("error_type", "")
        new_error_message = (
            error_message if error_message is not None else existing.get("error_message", "")
        )
        now = utc_now()
        finished_at = now if finished or new_status in {"completed", "failed", "stopped"} else None
        started_at = now if new_status == "running" and not existing.get("started_at") else None
        with self._connector.connect() as conn:
            conn.execute(
                """
                UPDATE subagent_runs
                SET status = ?, score = ?, final_response = ?, metadata_json = ?,
                    child_run_id = ?, error_type = ?, error_message = ?,
                    started_at = COALESCE(started_at, ?), updated_at = ?,
                    finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (
                    new_status,
                    new_score,
                    new_response,
                    dumps(merged_meta),
                    new_child_run,
                    new_error_type,
                    new_error_message,
                    started_at,
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

    def list_old_completed_child_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM subagent_runs
                WHERE status IN ('completed', 'failed', 'stopped')
                ORDER BY finished_at ASC NULLS LAST, created_at ASC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [_hydrate(row) for row in rows]

    def truncate_large_child_outputs(self, *, max_chars: int = 4000) -> int:
        with self._connector.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, final_response
                FROM subagent_runs
                WHERE LENGTH(final_response) > ?
                """,
                (int(max_chars),),
            ).fetchall()
            for row in rows:
                text = str(row["final_response"] or "")
                truncated = text[: max(0, int(max_chars) - 3)].rstrip() + "..."
                conn.execute(
                    "UPDATE subagent_runs SET final_response = ?, updated_at = ? WHERE id = ?",
                    (truncated, utc_now(), row["id"]),
                )
        return len(rows)

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
        "role_id": row["role_id"],
        "agent_definition_id": row["agent_definition_id"],
        "team_id": row["team_id"],
        "team_run_id": row["team_run_id"],
        "team_task_id": row["team_task_id"],
        "workflow_run_id": row["workflow_run_id"],
        "phase_run_id": row["phase_run_id"],
        "workflow_phase_id": row["workflow_phase_id"],
        "approval_id": row["approval_id"],
        "task": row["task"],
        "status": row["status"],
        "score": float(row["score"]),
        "attempt_index": row["attempt_index"],
        "final_response": row["final_response"],
        "error_type": row["error_type"],
        "error_message": row["error_message"],
        "metadata": loads(row["metadata_json"]),
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "updated_at": row["updated_at"],
        "finished_at": row["finished_at"],
    }
