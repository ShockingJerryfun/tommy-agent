"""Compaction eval — pre-compact flush proposes user-stated facts."""

from __future__ import annotations

import uuid

from langchain_core.messages import AIMessage, HumanMessage

from ...memory_platform import EchoEmbedder, MemoryProvider, NullReranker
from .report import EvalReport


def eval_compaction(store) -> EvalReport:
    report = EvalReport(suite="compaction")
    agent_id = f"eval-{uuid.uuid4().hex[:6]}"
    session_id = f"eval-sess-{uuid.uuid4().hex[:6]}"
    store.create_session(session_id=session_id, agent_id=agent_id, title="eval")

    provider = MemoryProvider(
        store=store, embedder=EchoEmbedder(), reranker=NullReranker()
    )

    messages = [
        HumanMessage(content="Please remember that I drink coffee black with no sugar."),
        AIMessage(content="Got it."),
    ]
    output = provider.on_pre_compact_flush(
        agent_id=agent_id,
        session_id=session_id,
        run_id=None,
        messages=messages,
    )
    proposals = list(output.proposals or [])
    coffee = [m for m in proposals if "coffee" in str(m.get("content") or "").lower()]
    report.add(
        "remember_proposes_memory",
        passed=bool(coffee),
        detail=f"proposed_count={len(proposals)}",
    )
    return report
