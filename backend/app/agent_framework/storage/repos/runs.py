"""Run repository (lifecycle of a model invocation)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._base import (
    Connector,
    PostgresRow,
    dumps,
    loads,
    refresh_session_summary,
    utc_now,
)

VALID_RUN_STATUS = {"queued", "running", "completed", "cancelled", "interrupted", "error"}
ACTIVE_STATUS = {"queued", "running"}


class RunRepo:
    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def create_run(
        self,
        *,
        session_id: str,
        agent_id: str = "default",
        input: str,
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
        status: str = "queued",
    ) -> dict[str, Any]:
        if status not in VALID_RUN_STATUS:
            raise ValueError(f"Unsupported run status: {status}")
        rid = run_id or f"run-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO runs(
                    id, session_id, agent_id, status, input, metadata_json,
                    assistant_message_id, cancel_requested, created_at, started_at,
                    updated_at, finished_at, error
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, 0, ?, NULL, ?, NULL, '')
                """,
                (rid, session_id, agent_id, status, input, dumps(metadata), now, now),
            )
        run = self.get_run(rid)
        if run is None:
            raise RuntimeError(f"Run was not created: {rid}")
        return run

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._run_from_row(row) if row is not None else None

    def update_run_status(
        self,
        run_id: str,
        *,
        status: str | None = None,
        assistant_message_id: str | None = None,
        error: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        updates: list[str] = ["updated_at = ?"]
        params: list[Any] = [utc_now()]
        if status is not None:
            if status not in VALID_RUN_STATUS:
                raise ValueError(f"Unsupported run status: {status}")
            updates.append("status = ?")
            params.append(status)
        if assistant_message_id is not None:
            updates.append("assistant_message_id = ?")
            params.append(assistant_message_id)
        if error is not None:
            updates.append("error = ?")
            params.append(error)
        if started_at is not None:
            updates.append("started_at = ?")
            params.append(started_at)
        if finished_at is not None:
            updates.append("finished_at = ?")
            params.append(finished_at)
        if metadata is not None:
            updates.append("metadata_json = ?")
            params.append(dumps(metadata))
        params.append(run_id)
        with self._connector.connect() as conn:
            row = conn.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            conn.execute(
                f"UPDATE runs SET {', '.join(updates)} WHERE id = ?",
                tuple(params),
            )
        return self.get_run(run_id)

    def request_run_cancel(self, run_id: str) -> dict[str, Any] | None:
        now = utc_now()
        with self._connector.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE runs
                SET cancel_requested = 1, updated_at = ?
                WHERE id = ?
                """,
                (now, run_id),
            )
            conn.execute(
                """
                INSERT INTO run_controls(
                    id, session_id, status, stop_reason,
                    started_at, updated_at, stop_requested_at
                )
                VALUES (?, ?, 'stopping', '用户已停止本次运行', ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = CASE
                        WHEN run_controls.status IN ('completed', 'error', 'stopped')
                            THEN run_controls.status
                        ELSE 'stopping'
                    END,
                    stop_reason = CASE
                        WHEN run_controls.stop_reason != ''
                            THEN run_controls.stop_reason
                        ELSE '用户已停止本次运行'
                    END,
                    updated_at = excluded.updated_at,
                    stop_requested_at = COALESCE(
                        run_controls.stop_requested_at,
                        excluded.stop_requested_at
                    )
                """,
                (run_id, row["session_id"], row["started_at"] or now, now, now),
            )
            conn.execute(
                """
                UPDATE approval_requests
                SET status = 'rejected',
                    error = 'Run was cancelled by user',
                    resolved_at = ?
                WHERE run_id = ? AND status = 'pending'
                """,
                (now, run_id),
            )
        return self.get_run(run_id)

    def is_run_cancel_requested(self, run_id: str) -> bool:
        if not run_id:
            return False
        with self._connector.connect() as conn:
            row = conn.execute(
                "SELECT cancel_requested, status FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return bool(
            row
            and (
                int(row["cancel_requested"] or 0) == 1
                or row["status"] in {"cancelled", "interrupted"}
            )
        )

    def list_runs(self, session_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM runs
                WHERE session_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def get_latest_run(self, session_id: str) -> dict[str, Any] | None:
        runs = self.list_runs(session_id, limit=1)
        return runs[0] if runs else None

    def get_active_run(self, session_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM runs
                WHERE session_id = ?
                  AND status IN ('queued', 'running')
                  AND finished_at IS NULL
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        return self._run_from_row(row) if row is not None else None

    def list_active_runs(
        self,
        *,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        session_clause = ""
        if session_id is not None:
            session_clause = "AND session_id = ?"
            params.append(session_id)
        params.append(limit)
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM runs
                WHERE status IN ('queued', 'running')
                  AND finished_at IS NULL
                  {session_clause}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def list_inflight_runs(
        self,
        *,
        session_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        session_clause = ""
        if session_id is not None:
            session_clause = "AND session_id = ?"
            params.append(session_id)
        params.append(limit)
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM runs
                WHERE status IN ('queued', 'running')
                  AND finished_at IS NULL
                  {session_clause}
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def finalize_run_as_interrupted(
        self,
        run_id: str,
        *,
        reason: str = "服务进程重启或连接断开后，运行已中断。",
    ) -> dict[str, Any] | None:
        now = utc_now()
        event_id = f"evt-{uuid4().hex}"
        agent_event: dict[str, Any] = {
            "type": "interrupted",
            "data": {"status": "interrupted", "reason": reason},
        }
        payload: dict[str, Any] = {
            **agent_event["data"],
            "run_id": run_id,
            "agent_event": agent_event,
        }
        with self._connector.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            if row["finished_at"] is not None:
                return self._run_from_row(row)
            if row["status"] not in ACTIVE_STATUS:
                return self._run_from_row(row)
            session_id = str(row["session_id"])
            sequence = (
                conn.execute(
                    "SELECT COALESCE(MAX(sequence), -1) + 1 FROM run_events WHERE session_id = ?",
                    (session_id,),
                ).fetchone()[0]
                or 0
            )
            conn.execute(
                """
                INSERT INTO run_events(
                    id, session_id, run_id, type, label, status,
                    payload_json, sequence, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    session_id,
                    run_id,
                    "agent",
                    "生成已停止",
                    "done",
                    dumps(payload),
                    sequence,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE runs
                SET status = 'interrupted',
                    finished_at = ?,
                    updated_at = ?,
                    error = ?
                WHERE id = ?
                """,
                (now, now, reason, run_id),
            )
            assistant_message_id = row["assistant_message_id"]
            if assistant_message_id:
                mrow = conn.execute(
                    "SELECT id, session_id, metadata_json FROM messages WHERE id = ?",
                    (assistant_message_id,),
                ).fetchone()
                if mrow is not None:
                    meta = loads(mrow["metadata_json"])
                    meta["status"] = "interrupted"
                    conn.execute(
                        "UPDATE messages SET metadata_json = ? WHERE id = ?",
                        (dumps(meta), assistant_message_id),
                    )
                    refresh_session_summary(conn, str(mrow["session_id"]))
            rc = conn.execute(
                "SELECT * FROM run_controls WHERE session_id = ? AND id = ?",
                (session_id, run_id),
            ).fetchone()
            if rc is not None:
                conn.execute(
                    """
                    UPDATE run_controls
                    SET status = 'stopped',
                        stop_reason = ?,
                        updated_at = ?
                    WHERE session_id = ? AND id = ?
                    """,
                    (reason, now, session_id, run_id),
                )
        return self.get_run(run_id)

    @staticmethod
    def _run_from_row(row: PostgresRow) -> dict[str, Any]:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "agent_id": row["agent_id"],
            "status": row["status"],
            "input": row["input"],
            "metadata": loads(row["metadata_json"]),
            "assistant_message_id": row["assistant_message_id"],
            "cancel_requested": bool(row["cancel_requested"]),
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "updated_at": row["updated_at"],
            "finished_at": row["finished_at"],
            "error": row["error"],
        }
