"""Workflow spec and run persistence repositories."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._base import Connector, dumps, loads, utc_now


class WorkflowSpecRepo:
    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def upsert(
        self,
        *,
        spec_id: str,
        name: str,
        description: str = "",
        spec: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_specs(
                    id, name, description, spec_json, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    spec_json = excluded.spec_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (spec_id, name, description, dumps(spec), dumps(metadata), now, now),
            )
        return self.get(spec_id) or {}

    def get(self, spec_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute("SELECT * FROM workflow_specs WHERE id = ?", (spec_id,)).fetchone()
        if row is None:
            return None
        return dict(row) | {
            "spec": loads(row["spec_json"]),
            "metadata": loads(row["metadata_json"]),
        }


class WorkflowRunRepo:
    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def create(
        self,
        *,
        spec_id: str,
        parent_session_id: str,
        parent_run_id: str,
        inputs: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = f"workflow-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_runs(
                    id, spec_id, parent_session_id, parent_run_id, status, summary,
                    inputs_json, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'queued', '', ?, ?, ?, ?)
                """,
                (
                    run_id,
                    spec_id,
                    parent_session_id,
                    parent_run_id,
                    dumps(inputs),
                    dumps(metadata),
                    now,
                    now,
                ),
            )
        return self.get(run_id) or {}

    def update(
        self,
        run_id: str,
        *,
        status: str | None = None,
        summary: str | None = None,
        metadata_patch: dict[str, Any] | None = None,
        finished: bool = False,
    ) -> dict[str, Any] | None:
        existing = self.get(run_id)
        if existing is None:
            return None
        metadata = dict(existing.get("metadata") or {})
        if metadata_patch:
            metadata.update(metadata_patch)
        new_status = status or existing["status"]
        now = utc_now()
        finished_at = now if finished or new_status in {"completed", "failed", "stopped"} else None
        with self._connector.connect() as conn:
            conn.execute(
                """
                UPDATE workflow_runs
                SET status = ?, summary = ?, metadata_json = ?, updated_at = ?,
                    finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (
                    new_status,
                    summary if summary is not None else existing["summary"],
                    dumps(metadata),
                    now,
                    finished_at,
                    run_id,
                ),
            )
        return self.get(run_id)

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return dict(row) | {
            "inputs": loads(row["inputs_json"]),
            "metadata": loads(row["metadata_json"]),
        }


class WorkflowPhaseRunRepo:
    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def create(
        self,
        *,
        workflow_run_id: str,
        phase_id: str,
        kind: str,
        agent: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = f"phase-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_phase_runs(
                    id, workflow_run_id, phase_id, kind, agent, status, outputs_json,
                    metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'queued', '[]', ?, ?, ?)
                """,
                (run_id, workflow_run_id, phase_id, kind, agent, dumps(metadata), now, now),
            )
        return self.get(run_id) or {}

    def update(
        self,
        phase_run_id: str,
        *,
        status: str | None = None,
        outputs: list[str] | None = None,
        finished: bool = False,
    ) -> dict[str, Any] | None:
        existing = self.get(phase_run_id)
        if existing is None:
            return None
        new_status = status or existing["status"]
        now = utc_now()
        finished_at = now if finished or new_status in {"completed", "failed", "stopped"} else None
        with self._connector.connect() as conn:
            conn.execute(
                """
                UPDATE workflow_phase_runs
                SET status = ?, outputs_json = ?, updated_at = ?,
                    finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (
                    new_status,
                    dumps(outputs if outputs is not None else existing["outputs"]),
                    now,
                    finished_at,
                    phase_run_id,
                ),
            )
        return self.get(phase_run_id)

    def get(self, phase_run_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_phase_runs WHERE id = ?",
                (phase_run_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(row) | {
            "outputs": loads(row["outputs_json"]) or [],
            "metadata": loads(row["metadata_json"]),
        }


class WorkflowWorkerRunRepo:
    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def create(
        self,
        *,
        workflow_run_id: str,
        phase_run_id: str,
        worker_index: int,
        task_id: str,
        role: str,
        status: str,
        output: str,
        subagent_run_id: str = "",
        child_session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = f"workflow-worker-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_worker_runs(
                    id, workflow_run_id, phase_run_id, worker_index, task_id,
                    subagent_run_id, child_session_id, role, status, output,
                    metadata_json, created_at, updated_at, finished_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    workflow_run_id,
                    phase_run_id,
                    int(worker_index),
                    task_id,
                    subagent_run_id,
                    child_session_id,
                    role,
                    status,
                    output,
                    dumps(metadata),
                    now,
                    now,
                    now,
                ),
            )
        return self.get(run_id) or {}

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_worker_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return _hydrate_worker(row) if row is not None else None

    def list_for_run(self, workflow_run_id: str) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM workflow_worker_runs
                WHERE workflow_run_id = ?
                ORDER BY created_at ASC, worker_index ASC
                """,
                (workflow_run_id,),
            ).fetchall()
        return [_hydrate_worker(row) for row in rows]


def _hydrate_worker(row: Any) -> dict[str, Any]:
    return dict(row) | {"metadata": loads(row["metadata_json"])}
