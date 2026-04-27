"""Audit log for the memory platform pipelines."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._base import Connector, dumps, loads, utc_now


class ConsolidationRunRepo:
    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def append(
        self,
        *,
        agent_id: str,
        kind: str,
        session_id: str | None = None,
        run_id: str | None = None,
        inputs_count: int = 0,
        outputs_count: int = 0,
        summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record_id = f"mcr-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_consolidation_runs(
                    id, agent_id, session_id, run_id, kind,
                    inputs_count, outputs_count, summary, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    agent_id,
                    session_id,
                    run_id,
                    kind,
                    int(inputs_count),
                    int(outputs_count),
                    summary,
                    dumps(metadata),
                    now,
                ),
            )
        return {
            "id": record_id,
            "agent_id": agent_id,
            "session_id": session_id,
            "run_id": run_id,
            "kind": kind,
            "inputs_count": inputs_count,
            "outputs_count": outputs_count,
            "summary": summary,
            "metadata": metadata or {},
            "created_at": now,
        }

    def list(
        self,
        *,
        agent_id: str | None = None,
        kind: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM memory_consolidation_runs
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [
            dict(row) | {"metadata": loads(row.get("metadata_json", "{}"))}
            for row in rows
        ]
