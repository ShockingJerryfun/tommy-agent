"""First-class multi-agent artifact references."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._base import Connector, dumps, loads, utc_now


class ArtifactRepo:
    SELECT_COLUMNS = (
        "id, owner_run_id, owner_type, subagent_run_id, team_run_id, workflow_run_id, "
        "kind, uri, path, sha256, size_bytes, summary, metadata_json, created_at"
    )

    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def create(
        self,
        *,
        owner_run_id: str,
        owner_type: str,
        kind: str,
        uri: str = "",
        path: str = "",
        sha256: str = "",
        size_bytes: int = 0,
        summary: str = "",
        subagent_run_id: str = "",
        team_run_id: str = "",
        workflow_run_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        artifact_id = f"artifact-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO artifacts(
                    id, owner_run_id, owner_type, subagent_run_id, team_run_id,
                    workflow_run_id, kind, uri, path, sha256, size_bytes, summary,
                    metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    owner_run_id,
                    owner_type,
                    subagent_run_id,
                    team_run_id,
                    workflow_run_id,
                    kind,
                    uri,
                    path,
                    sha256,
                    int(size_bytes),
                    summary,
                    dumps(metadata),
                    now,
                ),
            )
        return self.get(artifact_id) or {}

    def get(self, artifact_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute(
                f"SELECT {self.SELECT_COLUMNS} FROM artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
        return _hydrate(row) if row is not None else None

    def list_for_owner(self, owner_run_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM artifacts
                WHERE owner_run_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (owner_run_id, int(limit)),
            ).fetchall()
        return [_hydrate(row) for row in rows]

    def list_for_subagent(self, subagent_run_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM artifacts
                WHERE subagent_run_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (subagent_run_id, int(limit)),
            ).fetchall()
        return [_hydrate(row) for row in rows]

    def list_orphan_artifacts(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM artifacts
                WHERE subagent_run_id <> ''
                  AND NOT EXISTS (
                      SELECT 1 FROM subagent_runs WHERE subagent_runs.id = artifacts.subagent_run_id
                  )
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [_hydrate(row) for row in rows]

    def delete_orphan_artifacts(self, *, limit: int = 100) -> int:
        orphans = self.list_orphan_artifacts(limit=limit)
        if not orphans:
            return 0
        with self._connector.connect() as conn:
            for artifact in orphans:
                conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact["id"],))
        return len(orphans)


def _hydrate(row: Any) -> dict[str, Any]:
    return dict(row) | {"metadata": loads(row["metadata_json"])}
