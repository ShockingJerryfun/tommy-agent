"""Hybrid memory retriever — FTS + pgvector fused with Reciprocal Rank Fusion.

For a query ``q`` we run two independent searches:

1. ``MemoryRepo.search_fts(q)`` — Postgres ``plainto_tsquery`` with
   ``ts_rank_cd``.
2. ``MemoryRepo.search_vector(embed(q))`` — HNSW cosine NN on the
   ``embedding`` column.

We fuse them via Reciprocal Rank Fusion (Cormack et al. 2009):

    rrf(d) = sum over rankers r of  1 / (k + rank_r(d))

with ``k = 60`` by default. RRF is robust to score-distribution
differences between the two rankers and is the standard choice across
hybrid-search systems (Vespa, Elasticsearch ``rrf``, OpenSearch, etc.).

After fusion we optionally invoke a cross-encoder reranker (see
``reranker.py``); the final list is truncated to ``top_k``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .candidates import MemoryCandidate
from .embedder import Embedder, NullEmbedder
from .reranker import NullReranker, Reranker


@dataclass(frozen=True)
class RetrievalResult:
    candidates: list[MemoryCandidate]
    diagnostics: dict[str, Any] = field(default_factory=dict)


class HybridRetriever:
    """Combine FTS + vector search via RRF, then optional rerank."""

    def __init__(
        self,
        store: Any,
        *,
        embedder: Embedder | None = None,
        reranker: Reranker | None = None,
        rrf_k: int = 60,
        fts_limit: int = 20,
        vector_limit: int = 20,
    ) -> None:
        self.store = store
        self.embedder: Embedder = embedder or NullEmbedder()
        self.reranker: Reranker = reranker or NullReranker()
        self.rrf_k = max(1, int(rrf_k))
        self.fts_limit = max(1, int(fts_limit))
        self.vector_limit = max(1, int(vector_limit))

    # ----------------------------------------------------------- retrieval

    def retrieve(
        self,
        query: str,
        *,
        agent_id: str,
        top_k: int = 5,
        rerank: bool = True,
    ) -> RetrievalResult:
        if not query or not query.strip():
            return RetrievalResult(candidates=[], diagnostics={"reason": "empty_query"})

        memories_repo = getattr(self.store, "memories", self.store)

        fts_rows = memories_repo.search_fts(agent_id=agent_id, query=query, limit=self.fts_limit)
        embedding = self.embedder.embed(query)
        vector_rows = (
            memories_repo.search_vector(
                agent_id=agent_id, embedding=embedding, limit=self.vector_limit
            )
            if embedding
            else []
        )

        candidates = self._fuse(fts_rows, vector_rows)
        if rerank and candidates:
            ranked = self.reranker.rerank(query, candidates, top_k=top_k)
            if ranked:
                candidates = ranked
        candidates = candidates[: max(0, top_k)]

        # Touch usage stats so the Forgetter's decay path can deprioritise
        # stale items. Best-effort; never raise into the caller.
        for candidate in candidates:
            try:
                memories_repo.touch(candidate.id)
            except Exception:  # noqa: BLE001 - audit only
                continue

        diagnostics = {
            "fts_count": len(fts_rows),
            "vector_count": len(vector_rows),
            "embedded": bool(embedding),
            "rrf_k": self.rrf_k,
            "reranker": getattr(self.reranker, "name", type(self.reranker).__name__),
            "embedder_model": self.embedder.model,
        }
        return RetrievalResult(candidates=candidates, diagnostics=diagnostics)

    # -------------------------------------------------------------- fusion

    def _fuse(
        self,
        fts_rows: list[dict[str, Any]],
        vector_rows: list[dict[str, Any]],
    ) -> list[MemoryCandidate]:
        """Reciprocal Rank Fusion across the two ranker outputs."""

        scores: dict[str, float] = {}
        meta: dict[str, dict[str, Any]] = {}
        rrf_k = self.rrf_k

        for position, row in enumerate(fts_rows):
            mid = str(row.get("id"))
            if not mid:
                continue
            scores[mid] = scores.get(mid, 0.0) + 1.0 / (rrf_k + position + 1)
            row_meta = meta.setdefault(mid, {"row": row})
            row_meta["fts_position"] = position
            row_meta["fts_rank"] = float(row.get("fts_rank") or 0.0)

        for position, row in enumerate(vector_rows):
            mid = str(row.get("id"))
            if not mid:
                continue
            scores[mid] = scores.get(mid, 0.0) + 1.0 / (rrf_k + position + 1)
            row_meta = meta.setdefault(mid, {"row": row})
            row_meta["vector_position"] = position
            row_meta["vector_score"] = float(row.get("vector_score") or 0.0)

        fused: list[MemoryCandidate] = []
        for mid, score in scores.items():
            row = meta[mid]["row"]
            candidate = MemoryCandidate(
                id=mid,
                content=str(row.get("content") or ""),
                status=str(row.get("status") or "active"),
                source_session_id=row.get("source_session_id"),
                metadata=row.get("metadata") or {},
                fts_rank=meta[mid].get("fts_rank"),
                fts_position=meta[mid].get("fts_position"),
                vector_score=meta[mid].get("vector_score"),
                vector_position=meta[mid].get("vector_position"),
                rrf_score=score,
                final_score=score,
                importance=float(row.get("importance") or 0.5),
                last_used_at=row.get("last_used_at"),
            )
            fused.append(candidate)

        # Stable, deterministic ordering: RRF score desc, importance desc,
        # id asc as the final tiebreak.
        fused.sort(
            key=lambda c: (-c.rrf_score, -c.importance, c.id),
        )
        # Make sure final_score == rrf_score before optional rerank.
        return [replace(c, final_score=c.rrf_score) for c in fused]
