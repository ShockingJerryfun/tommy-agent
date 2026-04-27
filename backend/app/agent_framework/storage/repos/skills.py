"""Skill proposal + version repository."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._base import Connector, PostgresRow, dumps, loads, utc_now


class SkillRepo:
    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def create_skill_proposal(
        self,
        *,
        agent_id: str,
        name: str,
        relative_path: str,
        action: str,
        rationale: str,
        content: str,
        risks: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "proposed",
    ) -> dict[str, Any]:
        proposal_id = f"skill-prop-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO skill_proposals(
                    id, agent_id, name, relative_path, action, rationale, content,
                    risks_json, metadata_json, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal_id,
                    agent_id,
                    name,
                    relative_path,
                    action,
                    rationale,
                    content,
                    dumps(risks or []),
                    dumps(metadata),
                    status,
                    now,
                    now,
                ),
            )
        return {
            "id": proposal_id,
            "agent_id": agent_id,
            "name": name,
            "relative_path": relative_path,
            "action": action,
            "rationale": rationale,
            "content": content,
            "risks": risks or [],
            "metadata": metadata or {},
            "status": status,
            "version_id": None,
            "created_at": now,
            "updated_at": now,
            "applied_at": None,
        }

    def get_skill_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute(
                "SELECT * FROM skill_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
        return self._proposal_row(row) if row is not None else None

    def list_skill_proposals(
        self,
        *,
        agent_id: str = "default",
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [agent_id]
        status_clause = ""
        if status:
            status_clause = "AND status = ?"
            params.append(status)
        params.append(limit)
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM skill_proposals
                WHERE agent_id = ? {status_clause}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._proposal_row(row) for row in rows]

    def apply_skill_proposal(
        self,
        proposal_id: str,
        *,
        version_id: str,
        previous_content: str,
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self._connector.connect() as conn:
            row = conn.execute(
                "SELECT * FROM skill_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                INSERT INTO skill_versions(
                    id, agent_id, name, relative_path, content,
                    previous_content, proposal_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    row["agent_id"],
                    row["name"],
                    row["relative_path"],
                    row["content"],
                    previous_content,
                    proposal_id,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE skill_proposals
                SET status = 'applied', version_id = ?, updated_at = ?, applied_at = ?
                WHERE id = ?
                """,
                (version_id, now, now, proposal_id),
            )
        return self.get_skill_proposal(proposal_id)

    def reject_skill_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        now = utc_now()
        with self._connector.connect() as conn:
            row = conn.execute(
                "SELECT * FROM skill_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE skill_proposals
                SET status = 'rejected', updated_at = ?
                WHERE id = ?
                """,
                (now, proposal_id),
            )
        return self.get_skill_proposal(proposal_id)

    def list_skill_versions(
        self,
        *,
        agent_id: str = "default",
        relative_path: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [agent_id]
        path_clause = ""
        if relative_path:
            path_clause = "AND relative_path = ?"
            params.append(relative_path)
        params.append(limit)
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM skill_versions
                WHERE agent_id = ? {path_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _proposal_row(row: PostgresRow) -> dict[str, Any]:
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "name": row["name"],
            "relative_path": row["relative_path"],
            "action": row["action"],
            "rationale": row["rationale"],
            "content": row["content"],
            "risks": loads(row["risks_json"]) if row["risks_json"] else [],
            "metadata": loads(row["metadata_json"]),
            "status": row["status"],
            "version_id": row["version_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "applied_at": row["applied_at"],
        }
