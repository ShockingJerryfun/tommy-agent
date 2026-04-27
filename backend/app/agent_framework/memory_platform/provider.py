"""High-level facade composing embedder + retriever + pipelines.

A single :class:`MemoryProvider` wires the moving parts together so the
rest of the runtime depends on one stable interface:

- :meth:`retrieve` — used by ``ContextBuilder`` to fill the
  ``retrieved_memory`` section.
- :meth:`reflect` / :meth:`consolidate` / :meth:`forget` — used by the
  scheduler / compaction path / future cron jobs.
- :meth:`on_pre_compact_flush` — wired into the run pipeline's
  compaction trigger so user-stated facts survive context compression.

The provider is cheap to instantiate (no heavy deps loaded eagerly),
which lets callers create one per :class:`PostgresAgentStore` instance.
"""

from __future__ import annotations

from typing import Any

from . import pipelines
from .candidates import MemoryCandidate
from .embedder import Embedder, make_embedder
from .reranker import Reranker, make_reranker
from .retriever import HybridRetriever, RetrievalResult


class MemoryProvider:
    def __init__(
        self,
        store: Any,
        *,
        embedder: Embedder | None = None,
        reranker: Reranker | None = None,
        retriever: HybridRetriever | None = None,
    ) -> None:
        self.store = store
        self.embedder: Embedder = embedder or make_embedder()
        self.reranker: Reranker = reranker or make_reranker()
        self.retriever: HybridRetriever = retriever or HybridRetriever(
            store, embedder=self.embedder, reranker=self.reranker
        )

    # ------------------------------------------------------------ retrieve

    def retrieve(
        self,
        query: str,
        *,
        agent_id: str,
        top_k: int = 5,
        rerank: bool = True,
    ) -> RetrievalResult:
        return self.retriever.retrieve(
            query, agent_id=agent_id, top_k=top_k, rerank=rerank
        )

    def retrieve_for_context(
        self,
        query: str,
        *,
        agent_id: str,
        top_k: int = 5,
    ) -> list[MemoryCandidate]:
        return self.retrieve(query, agent_id=agent_id, top_k=top_k).candidates

    # ----------------------------------------------------- write pipelines

    def reflect(
        self,
        *,
        agent_id: str,
        session_id: str | None,
        run_id: str | None,
        messages: list[Any],
    ) -> pipelines.ReflectorOutput:
        return pipelines.reflect_messages(
            self.store,
            agent_id=agent_id,
            session_id=session_id,
            run_id=run_id,
            messages=messages,
            embedder=self.embedder,
        )

    def consolidate(self, *, agent_id: str, limit: int = 200) -> pipelines.ConsolidationOutput:
        return pipelines.consolidate(self.store, agent_id=agent_id, limit=limit)

    def forget(
        self,
        *,
        agent_id: str,
        decay_step: float = 0.02,
        forget_threshold: float = -0.5,
        importance_floor: float = 0.6,
        limit: int = 200,
    ) -> pipelines.ForgetterOutput:
        return pipelines.apply_forgetting(
            self.store,
            agent_id=agent_id,
            decay_step=decay_step,
            forget_threshold=forget_threshold,
            importance_floor=importance_floor,
            limit=limit,
        )

    def on_pre_compact_flush(
        self,
        *,
        agent_id: str,
        session_id: str,
        run_id: str | None,
        messages: list[Any],
    ) -> pipelines.ReflectorOutput:
        return pipelines.flush_for_compaction(
            self.store,
            agent_id=agent_id,
            session_id=session_id,
            run_id=run_id,
            messages=messages,
            embedder=self.embedder,
        )

    # ------------------------------------------------------------ helpers

    def confirm(self, memory_id: str) -> dict[str, Any] | None:
        confirmed = self.store.confirm_memory(memory_id)
        if not confirmed:
            return None
        # Embed eagerly on confirmation so the next retrieval can use it.
        try:
            vec = self.embedder.embed(confirmed.get("content") or "")
            if vec:
                self.store.memories.update_embedding(
                    memory_id, embedding=vec, model=self.embedder.model
                )
        except Exception:  # noqa: BLE001 - best effort
            pass
        return confirmed


_DEFAULT_PROVIDER: MemoryProvider | None = None


def get_default_memory_provider(store: Any) -> MemoryProvider:
    """Lazy singleton tied to the supplied store.

    Re-instantiates if the store identity changes (rare; typically only
    in tests that use ``reset_for_tests``).
    """

    global _DEFAULT_PROVIDER
    if _DEFAULT_PROVIDER is None or _DEFAULT_PROVIDER.store is not store:
        _DEFAULT_PROVIDER = MemoryProvider(store)
    return _DEFAULT_PROVIDER


def reset_default_memory_provider() -> None:
    global _DEFAULT_PROVIDER
    _DEFAULT_PROVIDER = None
