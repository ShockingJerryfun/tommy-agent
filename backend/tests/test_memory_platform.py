"""End-to-end tests for the S2 memory platform.

Covers:

- FTS-only retrieval when no embedder is configured.
- Vector retrieval with a deterministic stub embedder.
- RRF fusion across both rankers.
- Reranker pluggability (NullReranker preserves RRF order; a stub
  reranker reorders by content-prefix match).
- Reflector extraction + memory_consolidation_runs audit row.
- Forgetter decay loop rejects low-importance, unused memories.
- ``on_pre_compact_flush`` writes a ``flush`` audit row and proposes
  memories for the soon-to-be-summarised tail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent_framework.memory_platform import (
    EchoEmbedder,
    HybridRetriever,
    MemoryProvider,
    NullEmbedder,
    NullReranker,
    extract_candidates,
    flush_for_compaction,
)
from app.agent_framework.memory_platform.candidates import MemoryCandidate
from app.agent_framework.memory_platform.pipelines import (
    apply_forgetting,
    reflect_messages,
)
from app.agent_framework.memory_platform.provider import (
    reset_default_memory_provider,
)
from app.agent_framework.store import PostgresAgentStore

# ---------------------------------------------------------------- helpers


@dataclass
class _Msg:
    role: str
    content: str


def _make_store_with_active_memory(
    *,
    embedder: Any | None = None,
) -> tuple[PostgresAgentStore, list[dict[str, Any]]]:
    store = PostgresAgentStore()
    store.reset_for_tests()
    reset_default_memory_provider()
    rows = []
    seeds = [
        ("Tommy's owner is Fang Jin and he lives in Shanghai.", 0.9),
        ("Fang Jin is the product owner driving the Tommy SOTA rebuild.", 0.85),
        ("Tommy uses LangGraph for agent orchestration.", 0.7),
        ("DeepSeek v4 Pro is the configured cognitive model.", 0.7),
        ("Pizza is delicious.", 0.4),
    ]
    for content, importance in seeds:
        row = store.create_memory(
            agent_id="default",
            content=content,
            status="active",
            importance=importance,
        )
        if embedder is not None:
            vec = embedder.embed(content)
            if vec:
                store.memories.update_embedding(
                    row["id"], embedding=vec, model=embedder.model
                )
        rows.append(row)
    return store, rows


# ------------------------------------------------------- retrieval paths


def test_fts_only_retrieval_returns_relevant_rows() -> None:
    store, _ = _make_store_with_active_memory()
    retriever = HybridRetriever(
        store, embedder=NullEmbedder(), reranker=NullReranker()
    )
    result = retriever.retrieve("Fang Jin owner", agent_id="default", top_k=3)

    assert result.candidates, "FTS should match seeds containing 'Fang Jin'"
    contents = " ".join(c.content for c in result.candidates)
    assert "Fang Jin" in contents
    # Without an embedder the diagnostics must reflect FTS-only mode.
    assert result.diagnostics["embedded"] is False
    assert result.diagnostics["vector_count"] == 0
    # FTS rank populated; vector_score absent.
    assert all(c.fts_rank is not None for c in result.candidates)
    assert all(c.vector_score is None for c in result.candidates)


def test_vector_retrieval_with_echo_embedder() -> None:
    embedder = EchoEmbedder()
    store, rows = _make_store_with_active_memory(embedder=embedder)

    retriever = HybridRetriever(
        store, embedder=embedder, reranker=NullReranker(), fts_limit=0
    )
    # Use the exact content of one row as the query so cosine == 1.
    target = rows[1]
    result = retriever.retrieve(target["content"], agent_id="default", top_k=3)

    assert result.candidates
    # Top hit should be the exact match.
    assert result.candidates[0].id == target["id"]
    assert result.diagnostics["embedded"] is True
    assert result.diagnostics["vector_count"] >= 1


def test_rrf_fusion_combines_both_rankers() -> None:
    embedder = EchoEmbedder()
    store, rows = _make_store_with_active_memory(embedder=embedder)
    retriever = HybridRetriever(store, embedder=embedder, reranker=NullReranker())
    result = retriever.retrieve("Fang Jin", agent_id="default", top_k=5)

    assert result.candidates
    # At least one candidate should have BOTH a FTS rank and a vector score
    # — that's the signal RRF actually fused two ranker outputs.
    has_both = any(
        c.fts_rank is not None and c.vector_score is not None
        for c in result.candidates
    )
    assert has_both, "expected at least one candidate ranked by both FTS and vector"
    # RRF scores are positive and ordered desc.
    scores = [c.rrf_score for c in result.candidates]
    assert all(s > 0 for s in scores)
    assert scores == sorted(scores, reverse=True)


class _PrefixReranker:
    """Stub reranker: prefers candidates whose content starts with the query."""

    name = "prefix"

    def rerank(
        self,
        query: str,
        candidates: list[MemoryCandidate],
        *,
        top_k: int,
    ) -> list[MemoryCandidate]:
        scored = []
        for cand in candidates:
            score = 1.0 if cand.content.lower().startswith(query.lower()) else 0.0
            scored.append((score, cand))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            MemoryCandidate(**{**c.__dict__, "rerank_score": s, "final_score": s})
            for s, c in scored[: max(0, top_k)]
        ]


def test_reranker_swaps_top_candidate() -> None:
    store, _ = _make_store_with_active_memory()
    retriever = HybridRetriever(
        store, embedder=NullEmbedder(), reranker=_PrefixReranker()
    )
    result = retriever.retrieve("Tommy", agent_id="default", top_k=3)
    assert result.candidates
    # First candidate must start with 'Tommy' because the reranker said so.
    assert result.candidates[0].content.lower().startswith("tommy")


# ------------------------------------------------------- pipelines


def test_extract_candidates_pulls_remember_lines() -> None:
    msgs = [
        _Msg("user", "Hello"),
        _Msg("user", "Please remember that my favorite color is blue."),
        _Msg("assistant", "Got it."),
        _Msg("user", "I am a senior engineer."),
        _Msg("user", "记住：我下周要去北京出差。"),
    ]
    candidates = extract_candidates(msgs)
    assert len(candidates) == 3
    joined = " | ".join(candidates).lower()
    assert "blue" in joined
    assert "engineer" in joined
    assert "北京" in " | ".join(candidates)


def test_reflect_messages_creates_proposals_and_audits() -> None:
    store = PostgresAgentStore()
    store.reset_for_tests()
    reset_default_memory_provider()
    session_id = store.create_session(agent_id="default")

    msgs = [_Msg("user", "Please remember my favorite color is blue.")]
    output = reflect_messages(
        store,
        agent_id="default",
        session_id=session_id,
        run_id="run-1",
        messages=msgs,
        embedder=None,
    )
    assert output.outputs_count == 1
    proposal = output.proposals[0]
    assert proposal["status"] == "proposed"
    assert "blue" in proposal["content"].lower()

    audit = store.consolidation_runs.list(agent_id="default", kind="reflect")
    assert audit and audit[0]["outputs_count"] == 1


def test_forgetter_decays_low_importance_unused_memory() -> None:
    store = PostgresAgentStore()
    store.reset_for_tests()
    # One sticky (high importance) and one transient (low importance).
    sticky = store.create_memory(
        agent_id="default", content="sticky fact", status="active", importance=0.9
    )
    transient = store.create_memory(
        agent_id="default",
        content="transient fact",
        status="active",
        importance=0.1,
    )

    # Drive decay way below the forget threshold for the transient row.
    for _ in range(40):
        apply_forgetting(
            store,
            agent_id="default",
            decay_step=0.1,
            forget_threshold=-0.5,
            importance_floor=0.6,
            limit=10,
        )

    listed = {
        row["id"]: row for row in store.list_memories(agent_id="default", limit=20)
    }
    assert listed[sticky["id"]]["status"] == "active"
    assert listed[transient["id"]]["status"] == "rejected"

    audit = store.consolidation_runs.list(agent_id="default", kind="forget")
    assert audit, "forgetter must record at least one audit row"


def test_on_pre_compact_flush_proposes_memories_and_audits() -> None:
    store = PostgresAgentStore()
    store.reset_for_tests()
    reset_default_memory_provider()
    session_id = store.create_session(agent_id="default")

    older_messages = [
        _Msg("user", "Please remember that I prefer concise answers."),
        _Msg("assistant", "Sure."),
        _Msg("user", "Remember: my company is called Acme."),
    ]
    output = flush_for_compaction(
        store,
        agent_id="default",
        session_id=session_id,
        run_id="run-x",
        messages=older_messages,
    )

    assert output.outputs_count == 2
    flush_runs = store.consolidation_runs.list(agent_id="default", kind="flush")
    assert flush_runs, "flush_for_compaction must write a 'flush' audit row"
    assert flush_runs[0]["session_id"] == session_id
    assert flush_runs[0]["run_id"] == "run-x"
    assert flush_runs[0]["outputs_count"] == 2

    proposed = store.list_memories(agent_id="default", status="proposed")
    contents = " ".join(item["content"].lower() for item in proposed)
    assert "concise" in contents
    assert "acme" in contents


# ------------------------------------------------------- provider facade


def test_provider_retrieve_for_context_shape() -> None:
    embedder = EchoEmbedder()
    store, _ = _make_store_with_active_memory(embedder=embedder)
    provider = MemoryProvider(store, embedder=embedder, reranker=NullReranker())

    candidates = provider.retrieve_for_context(
        "Fang Jin", agent_id="default", top_k=3
    )
    assert candidates
    for cand in candidates:
        assert isinstance(cand.id, str)
        assert isinstance(cand.content, str)
        assert cand.final_score >= 0.0
