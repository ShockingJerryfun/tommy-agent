"""Durable traces for selected skill activation feedback."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from ._base import Connector, loads, utc_now


class SkillActivationTraceRepo:
    SELECT_COLUMNS = (
        "id, session_id, run_id, snapshot_id, skill_id, skill_name, relative_path, "
        "required_tools_json, matched_tools_json, credited, terminal_status, "
        "terminal_reason, selected_json, created_at"
    )

    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def record_trace(
        self,
        *,
        session_id: str,
        run_id: str,
        snapshot_id: str,
        skill_id: str,
        skill_name: str = "",
        relative_path: str = "",
        required_tools: list[str] | None = None,
        matched_tools: list[str] | None = None,
        credited: bool = False,
        terminal_status: str = "",
        terminal_reason: str = "",
        selected: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        trace_id = f"sat-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            inserted = conn.execute(
                f"""
                INSERT INTO skill_activation_traces(
                    id, session_id, run_id, snapshot_id, skill_id, skill_name,
                    relative_path, required_tools_json, matched_tools_json, credited,
                    terminal_status, terminal_reason, selected_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, snapshot_id, skill_id) DO NOTHING
                RETURNING {self.SELECT_COLUMNS}
                """,
                (
                    trace_id,
                    session_id,
                    run_id,
                    snapshot_id,
                    skill_id,
                    skill_name,
                    relative_path,
                    _dump_json(required_tools or []),
                    _dump_json(matched_tools or []),
                    bool(credited),
                    terminal_status,
                    terminal_reason,
                    _dump_json(selected or {}),
                    now,
                ),
            ).fetchone()
            if inserted is not None:
                return _hydrate_trace_row(inserted), True
            existing = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM skill_activation_traces
                WHERE run_id = ? AND snapshot_id = ? AND skill_id = ?
                """,
                (run_id, snapshot_id, skill_id),
            ).fetchone()
        if existing is None:
            return {}, False
        return _hydrate_trace_row(existing), False

    def list_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM skill_activation_traces
                WHERE run_id = ?
                ORDER BY created_at ASC
                """,
                (run_id,),
            ).fetchall()
        return [_hydrate_trace_row(row) for row in rows]


def _hydrate_trace_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "run_id": row["run_id"],
        "snapshot_id": row["snapshot_id"],
        "skill_id": row["skill_id"],
        "skill_name": row["skill_name"],
        "relative_path": row["relative_path"],
        "required_tools": loads(row["required_tools_json"]),
        "matched_tools": loads(row["matched_tools_json"]),
        "credited": bool(row["credited"]),
        "terminal_status": row["terminal_status"],
        "terminal_reason": row["terminal_reason"],
        "selected": loads(row["selected_json"]),
        "created_at": row["created_at"],
    }


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
