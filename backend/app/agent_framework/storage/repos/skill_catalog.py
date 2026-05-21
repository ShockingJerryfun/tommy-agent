"""Active-skill catalog persistence (S5).

This repo owns the ``skills`` table — the activator's HNSW-indexed view
of the skills the agent currently has at its disposal. Lifecycle:

  Forge mine ──► register_skill (status='shadow')
                       │
                       ▼
              update_signature_embedding
                       │
                       ▼
              shadow_validate ── metrics_json ─► record_invocation*
                       │
                       ▼
                  set_status('active')   (human review queue)
                       │
                       ▼
                 search_signature ⇄ activator
                       │
                       ▼
                  set_status('retired')  (Forge retire pass)

The proposal/version changelog still lives in ``SkillRepo`` /
``skill_proposals`` / ``skill_versions``; both repos share the same
proposal_id/version_id where applicable.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._base import Connector, dumps, loads, utc_now


def _format_vector(values: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.7f}" for v in values) + "]"


class SkillCatalogRepo:
    SELECT_COLUMNS = (
        "id, agent_id, name, relative_path, description, signature, "
        "embedding_model, tool_chain_json, status, success_count, "
        "failure_count, invocation_count, avg_latency_ms, "
        "metrics_json, metadata_json, proposal_id, version_id, "
        "created_at, updated_at, last_used_at"
    )

    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    # -------------------------------------------------- writes
    def register_skill(
        self,
        *,
        agent_id: str,
        name: str,
        relative_path: str,
        signature: str,
        description: str = "",
        tool_chain: list[str] | None = None,
        status: str = "shadow",
        metadata: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        proposal_id: str | None = None,
        version_id: str | None = None,
    ) -> dict[str, Any]:
        skill_id = f"skill-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            row = conn.execute(
                f"""
                INSERT INTO skills(
                    id, agent_id, name, relative_path, description,
                    signature, tool_chain_json, status, metrics_json,
                    metadata_json, proposal_id, version_id,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id, relative_path) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    signature = EXCLUDED.signature,
                    tool_chain_json = EXCLUDED.tool_chain_json,
                    metrics_json = EXCLUDED.metrics_json,
                    metadata_json = EXCLUDED.metadata_json,
                    proposal_id = COALESCE(EXCLUDED.proposal_id, skills.proposal_id),
                    version_id = COALESCE(EXCLUDED.version_id, skills.version_id),
                    updated_at = EXCLUDED.updated_at
                RETURNING {self.SELECT_COLUMNS}
                """,
                (
                    skill_id,
                    agent_id,
                    name,
                    relative_path,
                    description,
                    signature,
                    dumps(tool_chain or []),
                    status,
                    dumps(metrics or {}),
                    dumps(metadata or {}),
                    proposal_id,
                    version_id,
                    now,
                    now,
                ),
            ).fetchone()
        return _hydrate_skill_row(row)

    def update_signature_embedding(
        self,
        skill_id: str,
        *,
        embedding: list[float],
        model: str,
    ) -> None:
        if not embedding:
            return
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                "UPDATE skills SET signature_embedding = ?::vector, "
                "embedding_model = ?, updated_at = ? WHERE id = ?",
                (_format_vector(embedding), model, now, skill_id),
            )

    def set_status(self, skill_id: str, status: str) -> dict[str, Any] | None:
        if status not in {"shadow", "active", "retired"}:
            raise ValueError(f"invalid skill status: {status}")
        now = utc_now()
        with self._connector.connect() as conn:
            row = conn.execute(
                f"""
                UPDATE skills SET status = ?, updated_at = ? WHERE id = ?
                RETURNING {self.SELECT_COLUMNS}
                """,
                (status, now, skill_id),
            ).fetchone()
        return _hydrate_skill_row(row) if row is not None else None

    def set_version(self, skill_id: str, version_id: str) -> dict[str, Any] | None:
        now = utc_now()
        with self._connector.connect() as conn:
            row = conn.execute(
                f"""
                UPDATE skills SET version_id = ?, updated_at = ? WHERE id = ?
                RETURNING {self.SELECT_COLUMNS}
                """,
                (version_id, now, skill_id),
            ).fetchone()
        return _hydrate_skill_row(row) if row is not None else None

    def update_metrics(
        self,
        skill_id: str,
        *,
        metrics: dict[str, Any],
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self._connector.connect() as conn:
            row = conn.execute(
                f"""
                UPDATE skills
                SET metrics_json = ?, updated_at = ?
                WHERE id = ?
                RETURNING {self.SELECT_COLUMNS}
                """,
                (dumps(metrics), now, skill_id),
            ).fetchone()
        return _hydrate_skill_row(row) if row is not None else None

    def record_invocation(
        self,
        skill_id: str,
        *,
        success: bool,
        latency_ms: float,
    ) -> dict[str, Any] | None:
        """Atomically increment counters and roll the average latency."""

        now = utc_now()
        with self._connector.connect() as conn:
            row = conn.execute(
                f"""
                UPDATE skills
                SET success_count = success_count + ?,
                    failure_count = failure_count + ?,
                    invocation_count = invocation_count + 1,
                    avg_latency_ms = (
                        (avg_latency_ms * invocation_count + ?)
                        / (invocation_count + 1)
                    ),
                    last_used_at = ?,
                    updated_at = ?
                WHERE id = ?
                RETURNING {self.SELECT_COLUMNS}
                """,
                (
                    1 if success else 0,
                    0 if success else 1,
                    float(latency_ms),
                    now,
                    now,
                    skill_id,
                ),
            ).fetchone()
        return _hydrate_skill_row(row) if row is not None else None

    # -------------------------------------------------- reads
    def get(self, skill_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute(
                f"SELECT {self.SELECT_COLUMNS} FROM skills WHERE id = ?",
                (skill_id,),
            ).fetchone()
        return _hydrate_skill_row(row) if row is not None else None

    def get_by_path(self, *, agent_id: str, relative_path: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS} FROM skills
                WHERE agent_id = ? AND relative_path = ?
                """,
                (agent_id, relative_path),
            ).fetchone()
        return _hydrate_skill_row(row) if row is not None else None

    def list_skills(
        self,
        *,
        agent_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [agent_id]
        clause = ""
        if status:
            clause = "AND status = ?"
            params.append(status)
        params.append(int(limit))
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM skills
                WHERE agent_id = ? {clause}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [_hydrate_skill_row(row) for row in rows]

    def search_signature(
        self,
        *,
        agent_id: str,
        embedding: list[float],
        limit: int = 5,
        statuses: tuple[str, ...] = ("active",),
    ) -> list[dict[str, Any]]:
        """Approximate-nearest-neighbor search via the HNSW index."""

        if not embedding:
            return []
        literal = _format_vector(embedding)
        # ``ANY`` with a Python tuple maps to PG array; build the placeholder
        # list inline for portability with the ?-style translator.
        status_placeholders = ", ".join(["?"] * len(statuses))
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS},
                       (signature_embedding <=> ?::vector) AS distance
                FROM skills
                WHERE agent_id = ?
                  AND status IN ({status_placeholders})
                  AND signature_embedding IS NOT NULL
                ORDER BY signature_embedding <=> ?::vector
                LIMIT ?
                """,
                (literal, agent_id, *statuses, literal, int(limit)),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            data = _hydrate_skill_row(row)
            data["distance"] = float(row["distance"])
            data["similarity"] = max(0.0, 1.0 - float(row["distance"]))
            results.append(data)
        return results


def _hydrate_skill_row(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        "id": row["id"],
        "agent_id": row["agent_id"],
        "name": row["name"],
        "relative_path": row["relative_path"],
        "description": row["description"],
        "signature": row["signature"],
        "embedding_model": row["embedding_model"],
        "tool_chain": loads(row["tool_chain_json"]) if row["tool_chain_json"] else [],
        "status": row["status"],
        "success_count": row["success_count"],
        "failure_count": row["failure_count"],
        "invocation_count": row["invocation_count"],
        "avg_latency_ms": float(row["avg_latency_ms"]),
        "metrics": loads(row["metrics_json"]),
        "metadata": loads(row["metadata_json"]),
        "proposal_id": row["proposal_id"],
        "version_id": row["version_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_used_at": row["last_used_at"],
    }
