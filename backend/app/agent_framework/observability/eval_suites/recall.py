"""Recall eval — does hybrid retrieval surface a seeded memory?"""

from __future__ import annotations

import uuid

from ...memory_platform import EchoEmbedder, MemoryProvider, NullReranker
from .report import EvalReport


def eval_recall(store) -> EvalReport:
    report = EvalReport(suite="recall")
    agent_id = f"eval-{uuid.uuid4().hex[:6]}"
    session_id = f"eval-sess-{uuid.uuid4().hex[:6]}"
    store.create_session(session_id=session_id, agent_id=agent_id, title="eval")

    provider = MemoryProvider(
        store=store,
        embedder=EchoEmbedder(),
        reranker=NullReranker(),
    )

    seeded_text = "The user prefers metric units when discussing distances."
    proposal = store.create_memory(
        agent_id=agent_id,
        content=seeded_text,
        status="active",
        source_session_id=session_id,
    )
    vec = provider.embedder.embed(seeded_text)
    if vec:
        store.memories.update_embedding(
            proposal["id"], embedding=vec, model=provider.embedder.model
        )

    candidates = provider.retrieve_for_context(
        "metric distance preferences",
        agent_id=agent_id,
        top_k=5,
    )
    found = any(c.id == proposal["id"] for c in candidates)
    report.add(
        "seeded_memory_recalled",
        passed=found,
        detail=f"candidates={len(candidates)}",
    )
    return report
