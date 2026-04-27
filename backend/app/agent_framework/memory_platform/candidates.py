"""Value objects exchanged between the retriever and the reranker."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemoryCandidate:
    id: str
    content: str
    status: str
    source_session_id: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    fts_rank: float | None = None
    fts_position: int | None = None
    vector_score: float | None = None
    vector_position: int | None = None
    rrf_score: float = 0.0
    rerank_score: float | None = None
    final_score: float = 0.0
    importance: float = 0.5
    last_used_at: str | None = None

    def to_injection_payload(self, *, query: str, rank: int) -> dict[str, Any]:
        return {
            "id": self.id,
            "memory_id": self.id,
            "status": self.status,
            "source_session_id": self.source_session_id,
            "content": self.content,
            "char_count": len(self.content),
            "rank": rank,
            "score": self.final_score,
            "rrf_score": self.rrf_score,
            "fts_rank": self.fts_rank,
            "vector_score": self.vector_score,
            "rerank_score": self.rerank_score,
            "query": query,
            "metadata": self.metadata or {},
        }
