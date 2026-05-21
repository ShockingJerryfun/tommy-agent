from __future__ import annotations

import logging
from typing import Any

from ..state import AgentState

logger = logging.getLogger(__name__)


def last_user_message(state: AgentState) -> str:
    for message in reversed(state.get("messages", [])):
        if getattr(message, "type", "") == "human":
            return str(getattr(message, "content", ""))
    return ""


def memory_snapshot(item: dict[str, Any], *, query: str, rank: int) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "memory_id": item.get("id"),
        "id": item.get("id"),
        "status": item.get("status"),
        "source_session_id": item.get("source_session_id"),
        "char_count": len(str(item.get("content") or "")),
        "rank": rank,
        "score": item.get("score") or item.get("final_score"),
        "rrf_score": item.get("rrf_score"),
        "fts_rank": item.get("fts_rank"),
        "vector_score": item.get("vector_score"),
        "rerank_score": item.get("rerank_score"),
        "query": query,
        "metadata": metadata,
    }


def recall_memories(
    *,
    store: Any,
    memory_provider: Any | None,
    agent_id: str,
    query: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    if not query:
        return []
    if memory_provider is not None:
        try:
            candidates = memory_provider.retrieve_for_context(query, agent_id=agent_id, top_k=top_k)
            return [
                {
                    "id": candidate.id,
                    "content": candidate.content,
                    "status": candidate.status,
                    "source_session_id": candidate.source_session_id,
                    "metadata": candidate.metadata,
                    "score": candidate.final_score,
                    "final_score": candidate.final_score,
                    "rrf_score": candidate.rrf_score,
                    "fts_rank": candidate.fts_rank,
                    "vector_score": candidate.vector_score,
                    "rerank_score": candidate.rerank_score,
                }
                for candidate in candidates
            ]
        except Exception as exc:  # noqa: BLE001 - prompt assembly falls back to text search.
            logger.debug("Memory provider recall failed; falling back to text search: %s", exc)
    return store.search_memories(agent_id=agent_id, query=query, limit=top_k)
