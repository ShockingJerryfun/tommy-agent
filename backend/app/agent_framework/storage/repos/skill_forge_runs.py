"""Audit log for the nightly Skill Forge."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._base import Connector, dumps, loads, utc_now


class SkillForgeRunRepo:
    SELECT_COLUMNS = (
        "id, agent_id, kind, inputs_count, proposals_count, "
        "summary, metrics_json, metadata_json, created_at"
    )

    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def append(
        self,
        *,
        agent_id: str,
        kind: str,
        inputs_count: int = 0,
        proposals_count: int = 0,
        summary: str = "",
        metrics: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if kind not in {"mine", "validate", "promote", "retire"}:
            raise ValueError(f"invalid forge run kind: {kind}")
        run_id = f"forge-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO skill_forge_runs(
                    id, agent_id, kind, inputs_count, proposals_count,
                    summary, metrics_json, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    agent_id,
                    kind,
                    int(inputs_count),
                    int(proposals_count),
                    summary,
                    dumps(metrics or {}),
                    dumps(metadata or {}),
                    now,
                ),
            )
        return {
            "id": run_id,
            "agent_id": agent_id,
            "kind": kind,
            "inputs_count": int(inputs_count),
            "proposals_count": int(proposals_count),
            "summary": summary,
            "metrics": metrics or {},
            "metadata": metadata or {},
            "created_at": now,
        }

    def list_runs(
        self,
        *,
        agent_id: str,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [agent_id]
        clause = ""
        if kind:
            clause = "AND kind = ?"
            params.append(kind)
        params.append(int(limit))
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM skill_forge_runs
                WHERE agent_id = ? {clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "agent_id": row["agent_id"],
                "kind": row["kind"],
                "inputs_count": row["inputs_count"],
                "proposals_count": row["proposals_count"],
                "summary": row["summary"],
                "metrics": loads(row["metrics_json"]),
                "metadata": loads(row["metadata_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
