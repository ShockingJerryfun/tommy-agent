"""Run-event repository."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._base import Connector, dumps, loads, utc_now


class EventRepo:
    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def append_run_event(
        self,
        session_id: str,
        *,
        run_id: str,
        type: str,
        label: str,
        status: str = "done",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        event_id = f"evt-{uuid4().hex}"
        with self._connector.connect() as conn:
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
                (event_id, session_id, run_id, type, label, status, dumps(payload), sequence, now),
            )
        return {
            "id": event_id,
            "session_id": session_id,
            "run_id": run_id,
            "type": type,
            "label": label,
            "status": status,
            "payload": payload or {},
            "sequence": sequence,
            "created_at": now,
        }

    def list_run_events_after(
        self,
        run_id: str,
        *,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [run_id]
        sequence_clause = ""
        if after_sequence is not None:
            sequence_clause = "AND sequence > ?"
            params.append(after_sequence)
        params.append(limit)
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, session_id, run_id, type, label, status,
                       payload_json, sequence, created_at
                FROM run_events
                WHERE run_id = ?
                  {sequence_clause}
                ORDER BY sequence ASC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [dict(row) | {"payload": loads(row["payload_json"])} for row in rows]

    def list_run_events(
        self,
        session_id: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT id, session_id, run_id, type, label, status, payload_json, sequence, created_at
            FROM run_events
            WHERE session_id = ?
            ORDER BY sequence ASC
        """
        params: tuple[Any, ...] = (session_id,)
        if limit is not None:
            sql = f"SELECT * FROM ({sql}) ORDER BY sequence DESC LIMIT ?"
            params = (session_id, limit)
        with self._connector.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        events = [dict(row) | {"payload": loads(row["payload_json"])} for row in rows]
        return sorted(events, key=lambda item: item["sequence"])

    def delete_events_before(self, cutoff_created_at: str, *, limit: int = 1000) -> int:
        with self._connector.connect() as conn:
            rows = conn.execute(
                """
                SELECT id
                FROM run_events
                WHERE created_at < ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (cutoff_created_at, int(limit)),
            ).fetchall()
            for row in rows:
                conn.execute("DELETE FROM run_events WHERE id = ?", (row["id"],))
        return len(rows)
