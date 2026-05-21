"""Tool call repository."""

from __future__ import annotations

from typing import Any

from ._base import Connector, dumps, loads, utc_now


class ToolCallRepo:
    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def upsert_tool_call(
        self,
        session_id: str,
        *,
        run_id: str,
        tool_call_id: str,
        name: str,
        status: str,
        args: dict[str, Any] | None = None,
        result: str | None = None,
    ) -> None:
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_calls(
                    id, session_id, run_id, name, status,
                    args_json, result, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    args_json = CASE
                        WHEN excluded.args_json != '{}' THEN excluded.args_json
                        ELSE tool_calls.args_json
                    END,
                    result = CASE
                        WHEN excluded.result != '' THEN excluded.result
                        ELSE tool_calls.result
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    tool_call_id,
                    session_id,
                    run_id,
                    name,
                    status,
                    dumps(args),
                    result or "",
                    now,
                    now,
                ),
            )

    def list_tool_calls(self, session_id: str) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id, session_id, run_id, name, status,
                    args_json, result, created_at, updated_at
                FROM tool_calls
                WHERE session_id = ?
                ORDER BY created_at ASC
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) | {"args": loads(row["args_json"])} for row in rows]

    def list_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id, session_id, run_id, name, status,
                    args_json, result, created_at, updated_at
                FROM tool_calls
                WHERE run_id = ?
                ORDER BY created_at ASC
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) | {"args": loads(row["args_json"])} for row in rows]
