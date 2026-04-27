"""Prompt-snapshot and memory-injection repositories.

Both tables back the audit trail for ContextBuilder v2:

- ``prompt_snapshots`` records *what* was sent to the model (sections,
  budget, content hash) so we can replay deterministically.
- ``memory_injections`` records *which memories* influenced a turn so the
  S2 reflector can later score retrieval quality.

Writes are intentionally append-only and do not raise on optional
metadata. ``record_snapshot`` performs the snapshot insert and any linked
memory-injection inserts in a single transaction so the two tables can
never disagree.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._base import Connector, dumps, loads, utc_now


class PromptSnapshotRepo:
    """Persists assembled prompts produced by ``ContextBuilder.build``."""

    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def record_snapshot(
        self,
        *,
        session_id: str,
        agent_id: str,
        run_id: str | None,
        model: str = "",
        total_chars: int,
        section_count: int,
        truncated_count: int,
        dropped_count: int,
        content_sha256: str,
        sections: list[dict[str, Any]],
        budget: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        injections: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        snapshot_id = f"prompt-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO prompt_snapshots(
                    id, session_id, run_id, agent_id, model,
                    total_chars, section_count, truncated_count, dropped_count,
                    content_sha256, sections_json, budget_json, metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    session_id,
                    run_id,
                    agent_id,
                    model,
                    int(total_chars),
                    int(section_count),
                    int(truncated_count),
                    int(dropped_count),
                    content_sha256,
                    dumps(sections),
                    dumps(budget),
                    dumps(metadata),
                    now,
                ),
            )
            for index, item in enumerate(injections or []):
                memory_id = str(item.get("memory_id") or item.get("id") or "")
                if not memory_id:
                    continue
                conn.execute(
                    """
                    INSERT INTO memory_injections(
                        id, snapshot_id, session_id, run_id, agent_id,
                        memory_id, query, rank, score, char_count,
                        metadata_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"inj-{uuid4().hex}",
                        snapshot_id,
                        session_id,
                        run_id,
                        agent_id,
                        memory_id,
                        str(item.get("query") or ""),
                        int(item.get("rank", index)),
                        item.get("score"),
                        int(item.get("char_count") or 0),
                        dumps(item.get("metadata")),
                        now,
                    ),
                )
        return {
            "id": snapshot_id,
            "session_id": session_id,
            "run_id": run_id,
            "agent_id": agent_id,
            "total_chars": total_chars,
            "section_count": section_count,
            "truncated_count": truncated_count,
            "dropped_count": dropped_count,
            "content_sha256": content_sha256,
            "created_at": now,
        }

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute(
                "SELECT * FROM prompt_snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            return None
        return _hydrate_snapshot_row(row)

    def list_snapshots(
        self,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM prompt_snapshots
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [_hydrate_snapshot_row(row) for row in rows]


class MemoryInjectionRepo:
    """Read access for ``memory_injections``.

    Writes go through :class:`PromptSnapshotRepo.record_snapshot` so the
    snapshot/injection pair stays atomic. This repo is read-only for now.
    """

    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def list_for_snapshot(self, snapshot_id: str) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_injections
                WHERE snapshot_id = ?
                ORDER BY rank ASC, created_at ASC
                """,
                (snapshot_id,),
            ).fetchall()
        return [_hydrate_injection_row(row) for row in rows]

    def list_for_session(
        self,
        session_id: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_injections
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, int(limit)),
            ).fetchall()
        return [_hydrate_injection_row(row) for row in rows]

    def list_for_memory(
        self,
        memory_id: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_injections
                WHERE memory_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (memory_id, int(limit)),
            ).fetchall()
        return [_hydrate_injection_row(row) for row in rows]


def _hydrate_snapshot_row(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["sections"] = loads(data.pop("sections_json", "[]")) or []
    data["budget"] = loads(data.pop("budget_json", "{}")) or {}
    data["metadata"] = loads(data.pop("metadata_json", "{}")) or {}
    return data


def _hydrate_injection_row(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["metadata"] = loads(data.pop("metadata_json", "{}")) or {}
    return data
