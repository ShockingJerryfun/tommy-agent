"""Context pact repository."""

from __future__ import annotations

from typing import Any

from ._base import Connector, dumps, loads, utc_now


class ContextPactRepo:
    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def get_context_pact(self, session_id: str, *, agent_id: str = "default") -> dict[str, Any]:
        with self._connector.connect() as conn:
            row = conn.execute(
                "SELECT pact_json FROM context_pacts WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return loads(row["pact_json"]) if row is not None else {}

    def upsert_context_pact(
        self,
        session_id: str,
        *,
        agent_id: str = "default",
        pact: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO context_pacts(session_id, agent_id, pact_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    agent_id = excluded.agent_id,
                    pact_json = excluded.pact_json,
                    updated_at = excluded.updated_at
                """,
                (session_id, agent_id, dumps(pact), now, now),
            )
        return pact
