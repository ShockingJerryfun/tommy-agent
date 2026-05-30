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
            **(payload or {}),
        }
        return self.store.events.append_run_event(
            session_id,
            run_id=parent_run_id,
            type=event_type,
            label=event_type,
            status=status,
            payload=event_payload,
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
            **(payload or {}),
        }
        return self.store.events.append_run_event(
            session_id,
            run_id=parent_run_id,
            type=event_type,
            label=event_type,
            status=status,
            payload=event_payload,
        )

    def list_for_parent_run(self, parent_run_id: str) -> list[dict[str, Any]]:
        return self.store.events.list_run_events_after(parent_run_id, limit=500)

    def list_for_team_run(self, team_run_id: str) -> list[dict[str, Any]]:
        return [
            event
            for event in self._list_all_events()
            if event.get("payload", {}).get("team_run_id") == team_run_id
        ]

    def list_for_workflow_run(self, workflow_run_id: str) -> list[dict[str, Any]]:
        return [
            event
            for event in self._list_all_events()
            if event.get("payload", {}).get("workflow_run_id") == workflow_run_id
        ]

    def _list_all_events(self) -> list[dict[str, Any]]:
        # Existing EventRepo requires a session for broad listing, so use a
        # bounded direct query here for cross-session multi-agent lookups.
        with self.store._connector.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, run_id, type, label, status,
                       payload_json, sequence, created_at
                FROM run_events
                ORDER BY sequence ASC
                LIMIT 500
                """
            ).fetchall()
        from ..storage.repos import loads

        return [dict(row) | {"payload": loads(row["payload_json"])} for row in rows]
