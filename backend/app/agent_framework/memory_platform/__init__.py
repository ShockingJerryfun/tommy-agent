"""Tommy memory platform — pgvector + FTS hybrid retrieval and the
reflector / consolidator / forgetter pipelines.

Public surface mirrors what the rest of the runtime imports today; deep
imports stay supported but are not part of the contract.
"""

from __future__ import annotations

from .candidates import MemoryCandidate
from .embedder import (
    EMBEDDING_DIM,
    EchoEmbedder,
    Embedder,
    NullEmbedder,
    OpenAIEmbedder,
    make_embedder,
)
from .pipelines import (
    ConsolidationOutput,
    ForgetterOutput,
    ReflectorOutput,
    apply_forgetting,
    consolidate,
    extract_candidates,
    flush_for_compaction,
    reflect_messages,
)
from .provider import (
    MemoryProvider,
    get_default_memory_provider,
    reset_default_memory_provider,
)
from .reranker import BgeReranker, NullReranker, Reranker, make_reranker
from .retriever import HybridRetriever, RetrievalResult

__all__ = [
    "EMBEDDING_DIM",
    "BgeReranker",
    "ConsolidationOutput",
    "EchoEmbedder",
    "Embedder",
    "ForgetterOutput",
    "HybridRetriever",
    "MemoryCandidate",
    "MemoryProvider",
    "NullEmbedder",
    "NullReranker",
    "OpenAIEmbedder",
    "ReflectorOutput",
    "Reranker",
    "RetrievalResult",
    "apply_forgetting",
    "consolidate",
    "extract_candidates",
    "flush_for_compaction",
    "get_default_memory_provider",
    "make_embedder",
    "make_reranker",
    "reflect_messages",
    "reset_default_memory_provider",
]
