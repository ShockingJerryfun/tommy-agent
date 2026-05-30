"""Progress event bridge for multi-agent team and workflow runs."""

from __future__ import annotations

from typing import Any

from ..storage import PostgresAgentStore


class EventBridge:
    def __init__(self, store: PostgresAgentStore) -> None:
        self.store = store

    def emit_team_event(
        self,
        event_type: str,
        *,
        session_id: str,
        parent_run_id: str,
        team_run_id: str,
        team_id: str = "",
        team_task_id: str = "",
        status: str = "done",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_payload = {
            "team_run_id": team_run_id,
            "team_id": team_id,
            "team_task_id": team_task_id,
            "service_status": status,
            **(payload or {}),
        }
        run_step_status = _run_step_status(status)
        return self.store.events.append_run_event(
            session_id,
            run_id=parent_run_id,
            type=event_type,
            label=event_type,
            status=run_step_status,
            payload={
                **event_payload,
                "agent_event": {
                    "type": event_type,
                    "data": {**event_payload, "status": run_step_status},
                },
            },
        )

    def emit_workflow_event(
        self,
        event_type: str,
        *,
        session_id: str,
        parent_run_id: str,
        workflow_run_id: str,
        phase_run_id: str = "",
        workflow_phase_id: str = "",
        worker_run_id: str = "",
        status: str = "done",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_payload = {
            "workflow_run_id": workflow_run_id,
            "phase_run_id": phase_run_id,
            "workflow_phase_id": workflow_phase_id,
            "worker_run_id": worker_run_id,
            "service_status": status,
            **(payload or {}),
        }
        run_step_status = _run_step_status(status)
        return self.store.events.append_run_event(
            session_id,
            run_id=parent_run_id,
            type=event_type,
            label=event_type,
            status=run_step_status,
            payload={
                **event_payload,
                "agent_event": {
                    "type": event_type,
                    "data": {**event_payload, "status": run_step_status},
                },
            },
        )

    def list_for_parent_run(self, parent_run_id: str) -> list[dict[str, Any]]:
        return self.store.events.list_run_events_after(parent_run_id, limit=500)

    def list_for_team_run(self, team_run_id: str) -> list[dict[str, Any]]:
        return self._list_events_containing(f'"team_run_id": "{team_run_id}"')

    def list_for_workflow_run(self, workflow_run_id: str) -> list[dict[str, Any]]:
        return self._list_events_containing(f'"workflow_run_id": "{workflow_run_id}"')

    def _list_events_containing(self, payload_fragment: str) -> list[dict[str, Any]]:
        with self.store._connector.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, run_id, type, label, status,
                       payload_json, sequence, created_at
                FROM run_events
                WHERE payload_json LIKE ?
                ESCAPE '\\'
                ORDER BY sequence ASC
                LIMIT 500
                """,
                (f"%{_escape_like(payload_fragment)}%",),
            ).fetchall()
        from ..storage.repos import loads

        return [dict(row) | {"payload": loads(row["payload_json"])} for row in rows]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _run_step_status(status: str) -> str:
    if status == "running":
        return "running"
    if status in {"failed", "error"}:
        return "error"
    return "done"
