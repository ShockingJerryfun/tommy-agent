"""Memory persistence — proposals, active recall, FTS + pgvector retrieval.

The repo carries the lifecycle columns introduced in S2 (`embedding`,
`embedding_model`, `fts`, `importance`, `last_used_at`, `use_count`,
`decay_score`). The hybrid retriever in
``app/agent_framework/memory_platform`` uses ``search_fts`` and
``search_vector`` directly; ``search_memories`` provides a simple ILIKE
fallback for exact text lookup.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._base import Connector, dumps, loads, utc_now


def _format_vector(values: list[float]) -> str:
    """Format a list of floats as the ``vector`` literal pgvector expects."""

    return "[" + ",".join(f"{float(v):.7f}" for v in values) + "]"


class MemoryRepo:
    SELECT_COLUMNS = (
        "id, agent_id, content, status, source_session_id, "
        "metadata_json, embedding_model, importance, last_used_at, "
        "use_count, decay_score, created_at, updated_at"
    )

    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    # ----------------------------------------------------------- writes

    def create_memory(
        self,
        *,
        agent_id: str,
        content: str,
        status: str = "proposed",
        source_session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        importance: float | None = None,
    ) -> dict[str, Any]:
        memory_id = f"mem-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO memories(
                    id, agent_id, content, status, source_session_id,
                    metadata_json, importance, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    agent_id,
                    content,
                    status,
                    source_session_id,
                    dumps(metadata),
                    float(importance) if importance is not None else 0.5,
                    now,
                    now,
                ),
            )
        return {
            "id": memory_id,
            "agent_id": agent_id,
            "content": content,
            "status": status,
            "source_session_id": source_session_id,
            "metadata": metadata or {},
            "importance": importance if importance is not None else 0.5,
            "use_count": 0,
            "decay_score": 0.0,
            "embedding_model": "",
            "last_used_at": None,
            "created_at": now,
            "updated_at": now,
        }

    def confirm_memory(self, memory_id: str) -> dict[str, Any] | None:
        return self.update_status(memory_id, status="active")

    def update_status(self, memory_id: str, *, status: str) -> dict[str, Any] | None:
        now = utc_now()
        with self._connector.connect() as conn:
            row = conn.execute(
                f"SELECT {self.SELECT_COLUMNS} FROM memories WHERE id = ?",
                (memory_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE memories SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, memory_id),
            )
        return _hydrate_memory_row(row) | {"status": status, "updated_at": now}

    def update_embedding(
        self,
        memory_id: str,
        *,
        embedding: list[float],
        model: str,
    ) -> None:
        if not embedding:
            return
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                "UPDATE memories SET embedding = ?::vector, embedding_model = ?, "
                "updated_at = ? WHERE id = ?",
                (_format_vector(embedding), model, now, memory_id),
            )

    def touch(self, memory_id: str) -> None:
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                UPDATE memories
                SET use_count = use_count + 1,
                    last_used_at = ?,
                    decay_score = LEAST(1.0, decay_score + 0.05)
                WHERE id = ?
                """,
                (now, memory_id),
            )

    def apply_decay(
        self,
        *,
        agent_id: str,
        decay_step: float = 0.02,
        forget_threshold: float = -0.5,
        importance_floor: float = 0.6,
        limit: int = 200,
    ) -> dict[str, int]:
        """Decay the score of active memories, forget the worst offenders.

        Memories with ``importance >= importance_floor`` never get forgotten,
        only their ``decay_score`` drifts. This keeps high-signal items
        sticky while letting transient observations age out.
        """

        now = utc_now()
        decayed = 0
        forgotten = 0
        with self._connector.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, importance, decay_score
                FROM memories
                WHERE agent_id = ? AND status = 'active'
                ORDER BY last_used_at NULLS FIRST, updated_at ASC
                LIMIT ?
                """,
                (agent_id, int(limit)),
            ).fetchall()
            for row in rows:
                new_score = float(row["decay_score"]) - decay_step
                if new_score < forget_threshold and float(row["importance"]) < importance_floor:
                    conn.execute(
                        "UPDATE memories SET status = 'rejected', updated_at = ?, "
                        "decay_score = ? WHERE id = ?",
                        (now, new_score, row["id"]),
                    )
                    forgotten += 1
                else:
                    conn.execute(
                        "UPDATE memories SET decay_score = ?, updated_at = ? WHERE id = ?",
                        (new_score, now, row["id"]),
                    )
                    decayed += 1
        return {"decayed": decayed, "forgotten": forgotten, "scanned": len(rows)}

    # ------------------------------------------------------------ reads

    def list_memories(
        self,
        *,
        agent_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [agent_id]
        status_clause = ""
        if status:
            status_clause = "AND status = ?"
            params.append(status)
        params.append(int(limit))
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM memories
                WHERE agent_id = ? {status_clause}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [_hydrate_memory_row(row) for row in rows]

    def search_memories(
        self,
        *,
        agent_id: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Legacy ILIKE search. New code should use ``search_fts`` /
        ``search_vector`` through the hybrid retriever.
        """

        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM memories
                WHERE agent_id = ? AND status = 'active' AND content ILIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (agent_id, f"%{query}%", int(limit)),
            ).fetchall()
        return [_hydrate_memory_row(row) for row in rows]

    def search_fts(
        self,
        *,
        agent_id: str,
        query: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Postgres full-text search ranked by ``ts_rank_cd``."""

        if not query.strip():
            return []
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS},
                       ts_rank_cd(fts, plainto_tsquery('simple', ?)) AS fts_rank
                FROM memories
                WHERE agent_id = ?
                  AND status = 'active'
                  AND fts @@ plainto_tsquery('simple', ?)
                ORDER BY fts_rank DESC, updated_at DESC
                LIMIT ?
                """,
                (query, agent_id, query, int(limit)),
            ).fetchall()
        return [
            _hydrate_memory_row(row) | {"fts_rank": float(row.get("fts_rank") or 0.0)}
            for row in rows
        ]

    def search_vector(
        self,
        *,
        agent_id: str,
        embedding: list[float],
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Approximate-nearest-neighbor search using the HNSW index."""

        if not embedding:
            return []
        literal = _format_vector(embedding)
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS},
                       (embedding <=> ?::vector) AS distance
                FROM memories
                WHERE agent_id = ?
                  AND status = 'active'
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> ?::vector
                LIMIT ?
                """,
                (literal, agent_id, literal, int(limit)),
            ).fetchall()
        return [
            _hydrate_memory_row(row)
            | {
                "distance": float(row.get("distance") or 0.0),
                # Convert cosine distance (0..2) into a 0..1 similarity score.
                "vector_score": max(0.0, 1.0 - float(row.get("distance") or 0.0)),
            }
            for row in rows
        ]

    def list_for_consolidation(
        self,
        *,
        agent_id: str,
        status: str = "proposed",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM memories
                WHERE agent_id = ? AND status = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (agent_id, status, int(limit)),
            ).fetchall()
        return [_hydrate_memory_row(row) for row in rows]


def _hydrate_memory_row(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    metadata = data.pop("metadata_json", None)
    if metadata is not None:
        data["metadata"] = loads(metadata)
    elif "metadata" not in data:
        data["metadata"] = {}
    # Drop columns the caller doesn't expect (e.g. raw fts vector).
    data.pop("fts", None)
    data.pop("embedding", None)
    return data
