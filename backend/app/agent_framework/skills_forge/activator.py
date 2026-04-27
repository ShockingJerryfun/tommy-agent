"""SkillActivator — HNSW-backed retrieval over the active skill catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..memory_platform import EMBEDDING_DIM, Embedder, make_embedder
from ..storage import get_agent_store
from ..store import PostgresAgentStore


@dataclass(frozen=True)
class SkillCandidate:
    """A single recall hit, ready to render in the system prompt."""

    skill_id: str
    name: str
    relative_path: str
    description: str
    signature: str
    tool_chain: list[str]
    status: str
    similarity: float
    distance: float
    metrics: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "relative_path": self.relative_path,
            "description": self.description,
            "signature": self.signature,
            "tool_chain": list(self.tool_chain),
            "status": self.status,
            "similarity": self.similarity,
            "distance": self.distance,
            "metrics": dict(self.metrics),
        }


class SkillActivator:
    """Embed-and-retrieve top-k skills relevant to a free-text query.

    The activator is intentionally read-only: writes (registration,
    metric updates) flow through :class:`SkillForge`. Keeping the two
    surfaces separate makes it cheap to pull the activator into the
    ContextBuilder without dragging the entire forge dependency graph.
    """

    def __init__(
        self,
        store: PostgresAgentStore | None = None,
        *,
        embedder: Embedder | None = None,
    ) -> None:
        self._store = store or get_agent_store()
        self._embedder = embedder or make_embedder()

    @property
    def embedder(self) -> Embedder:
        return self._embedder

    def recall(
        self,
        *,
        agent_id: str,
        query: str,
        k: int = 5,
        statuses: tuple[str, ...] = ("active",),
    ) -> list[SkillCandidate]:
        if not query or not query.strip():
            return []
        embedding = self._embedder.embed(query)
        if not embedding or len(embedding) != EMBEDDING_DIM:
            return []
        rows = self._store.skill_catalog.search_signature(
            agent_id=agent_id,
            embedding=embedding,
            limit=k,
            statuses=statuses,
        )
        return [_row_to_candidate(row) for row in rows]


def _row_to_candidate(row: dict[str, Any]) -> SkillCandidate:
    return SkillCandidate(
        skill_id=row["id"],
        name=row["name"],
        relative_path=row["relative_path"],
        description=row.get("description", ""),
        signature=row.get("signature", ""),
        tool_chain=list(row.get("tool_chain") or []),
        status=row.get("status", "active"),
        similarity=float(row.get("similarity", 0.0)),
        distance=float(row.get("distance", 1.0)),
        metrics=dict(row.get("metrics") or {}),
    )


_DEFAULT_ACTIVATOR: SkillActivator | None = None


def get_default_skill_activator(
    store: PostgresAgentStore | None = None,
) -> SkillActivator:
    global _DEFAULT_ACTIVATOR
    if _DEFAULT_ACTIVATOR is None:
        _DEFAULT_ACTIVATOR = SkillActivator(store=store)
    return _DEFAULT_ACTIVATOR
