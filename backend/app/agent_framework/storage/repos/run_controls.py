"""Run control repository (stop / start signaling for the run loop)."""

from __future__ import annotations

from typing import Any

from ._base import Connector, PostgresRow, utc_now


class RunControlRepo:
    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def start_run(self, session_id: str, *, run_id: str) -> dict[str, Any]:
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO run_controls(
                    id, session_id, status, stop_reason,
                    started_at, updated_at, stop_requested_at
                )
                VALUES (?, ?, 'running', '', ?, ?, NULL)
                ON CONFLICT(id) DO UPDATE SET
                    session_id = excluded.session_id,
                    status = 'running',
                    stop_reason = '',
                    updated_at = excluded.updated_at,
                    stop_requested_at = NULL
                """,
                (run_id, session_id, now, now),
            )
        return {
            "id": run_id,
            "session_id": session_id,
            "status": "running",
            "stop_reason": "",
            "started_at": now,
            "updated_at": now,
            "stop_requested_at": None,
        }

    def request_run_stop(
        self,
        session_id: str,
        *,
        run_id: str | None = None,
        reason: str = "Stopped by user",
    ) -> list[dict[str, Any]]:
        now = utc_now()
        params: list[Any] = [session_id]
        run_clause = ""
        if run_id:
            run_clause = "AND id = ?"
            params.append(run_id)

        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM run_controls
                WHERE session_id = ?
                  {run_clause}
                  AND status IN ('running', 'stopping')
                ORDER BY updated_at DESC
                """,
                tuple(params),
            ).fetchall()
            if not rows:
                return []

            run_ids = [str(row["id"]) for row in rows]
            placeholders = ",".join("?" for _ in run_ids)
            conn.execute(
                f"""
                UPDATE run_controls
                SET status = 'stopping',
                    stop_reason = ?,
                    stop_requested_at = COALESCE(stop_requested_at, ?),
                    updated_at = ?
                WHERE id IN ({placeholders})
                """,
                (reason, now, now, *run_ids),
            )
            conn.execute(
                f"""
                UPDATE approval_requests
                SET status = 'rejected',
                    error = ?,
                    resolved_at = ?
                WHERE session_id = ?
                  AND run_id IN ({placeholders})
                  AND status = 'pending'
                """,
                (reason, now, session_id, *run_ids),
            )
            updated_rows = conn.execute(
                f"""
                SELECT *
                FROM run_controls
                WHERE id IN ({placeholders})
                ORDER BY updated_at DESC
                """,
                tuple(run_ids),
            ).fetchall()
        return [self._row(row) for row in updated_rows]

    def run_stop_requested(self, *, session_id: str, run_id: str) -> bool:
        if not session_id or not run_id:
            return False
        with self._connector.connect() as conn:
            run_row = conn.execute(
                """
                SELECT cancel_requested, status
                FROM runs
                WHERE session_id = ? AND id = ?
                """,
                (session_id, run_id),
            ).fetchone()
            if run_row and (
                int(run_row["cancel_requested"] or 0) == 1
                or run_row["status"] in {"cancelled", "interrupted"}
            ):
                return True
            row = conn.execute(
                """
                SELECT status
                FROM run_controls
                WHERE session_id = ? AND id = ?
                """,
                (session_id, run_id),
            ).fetchone()
        return bool(row and row["status"] in {"stopping", "stopped"})

    def finish_run(
        self,
        session_id: str,
        *,
        run_id: str,
        status: str,
        reason: str = "",
    ) -> dict[str, Any] | None:
        if status not in {"stopped", "completed", "error"}:
            raise ValueError(f"Unsupported run status: {status}")
        now = utc_now()
        with self._connector.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM run_controls
                WHERE session_id = ? AND id = ?
                """,
                (session_id, run_id),
            ).fetchone()
            if row is None:
                return None
            next_status = "stopped" if row["status"] == "stopping" else status
            next_reason = reason or row["stop_reason"] or ""
            conn.execute(
                """
                UPDATE run_controls
                SET status = ?,
                    stop_reason = ?,
                    updated_at = ?
                WHERE session_id = ? AND id = ?
                """,
                (next_status, next_reason, now, session_id, run_id),
            )
        with self._connector.connect() as conn:
            updated = conn.execute(
                "SELECT * FROM run_controls WHERE session_id = ? AND id = ?",
                (session_id, run_id),
            ).fetchone()
        return self._row(updated) if updated is not None else None

    @staticmethod
    def _row(row: PostgresRow) -> dict[str, Any]:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "status": row["status"],
            "stop_reason": row["stop_reason"],
            "started_at": row["started_at"],
            "updated_at": row["updated_at"],
            "stop_requested_at": row["stop_requested_at"],
        }
