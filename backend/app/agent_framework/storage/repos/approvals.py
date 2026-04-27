"""Approval-request repository."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._base import Connector, PostgresRow, dumps, loads, utc_now


class ApprovalRepo:
    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def create_approval_request(
        self,
        *,
        session_id: str,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        args: dict[str, Any],
        risk_level: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        approval_id = f"approval-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO approval_requests(
                    id, session_id, run_id, tool_call_id, tool_name, args_json,
                    risk_level, summary, status, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    approval_id,
                    session_id,
                    run_id,
                    tool_call_id,
                    tool_name,
                    dumps(args),
                    risk_level,
                    summary,
                    dumps(metadata),
                    now,
                ),
            )
        return {
            "id": approval_id,
            "session_id": session_id,
            "run_id": run_id,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "args": args,
            "risk_level": risk_level,
            "summary": summary,
            "status": "pending",
            "result": "",
            "error": "",
            "metadata": metadata or {},
            "created_at": now,
            "resolved_at": None,
        }

    def get_approval_request(self, approval_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute(
                "SELECT * FROM approval_requests WHERE id = ?",
                (approval_id,),
            ).fetchone()
        return self._row(row) if row is not None else None

    def list_approval_requests(
        self,
        *,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM approval_requests
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._row(row) for row in rows]

    def resolve_approval_request(
        self,
        approval_id: str,
        *,
        status: str,
        result: str = "",
        error: str = "",
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self._connector.connect() as conn:
            row = conn.execute(
                "SELECT * FROM approval_requests WHERE id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE approval_requests
                SET status = ?, result = ?, error = ?, resolved_at = ?
                WHERE id = ?
                """,
                (status, result, error, now, approval_id),
            )
        return self.get_approval_request(approval_id)

    @staticmethod
    def _row(row: PostgresRow) -> dict[str, Any]:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "run_id": row["run_id"],
            "tool_call_id": row["tool_call_id"],
            "tool_name": row["tool_name"],
            "args": loads(row["args_json"]),
            "risk_level": row["risk_level"],
            "summary": row["summary"],
            "status": row["status"],
            "result": row["result"],
            "error": row["error"],
            "metadata": loads(row["metadata_json"]),
            "created_at": row["created_at"],
            "resolved_at": row["resolved_at"],
        }
