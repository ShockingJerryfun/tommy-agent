"""Cross-encoder reranker interface.

Decisions from blueprint §13:

- Ship ``BAAI/bge-reranker-base`` locally.

The reranker is intentionally optional: ``NullReranker`` returns the
candidates unchanged so unit tests, CI, and any environment without
``sentence-transformers``/``torch`` installed remain fast. The factory
``make_reranker()`` is opt-in via ``TOMMY_RERANKER`` and lazy-loads the
heavy deps only when first used.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import replace
from typing import Any, Protocol

from .candidates import MemoryCandidate


class Reranker(Protocol):
    name: str

    def rerank(
        self,
        query: str,
        candidates: list[MemoryCandidate],
        *,
        top_k: int,
    ) -> list[MemoryCandidate]: ...


class NullReranker:
    """Pass-through reranker; preserves the upstream RRF order."""

    name = "null"

    def rerank(
        self,
        query: str,  # noqa: ARG002 — interface
        candidates: list[MemoryCandidate],
        *,
        top_k: int,
    ) -> list[MemoryCandidate]:
        return list(candidates[: max(0, top_k)])


class BgeReranker:
    """``BAAI/bge-reranker-base`` cross-encoder.

    Lazy-loads ``sentence_transformers.CrossEncoder`` on first use so
    importing this module never pulls torch into the cold-start path.
    Caller is expected to keep a single instance per process; the model
    weights are ~280MB and take a couple seconds to materialise.
    """

    name = "bge-reranker-base"

    def __init__(
        self,
        *,
        model_name: str = "BAAI/bge-reranker-base",
        device: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self._model: Any | None = None

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import CrossEncoder  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover — exercised when dep missing
            raise RuntimeError(
                "sentence-transformers is required for BgeReranker; "
                "install it or set TOMMY_RERANKER=null."
            ) from exc
        kwargs: dict[str, Any] = {}
        if self.device:
            kwargs["device"] = self.device
        self._model = CrossEncoder(self.model_name, **kwargs)
        return self._model

    def rerank(
        self,
        query: str,
        candidates: list[MemoryCandidate],
        *,
        top_k: int,
    ) -> list[MemoryCandidate]:
        if not candidates:
            return []
        if not query.strip():
            return list(candidates[: max(0, top_k)])
        model = self._ensure_model()
        pairs: Iterable[tuple[str, str]] = ((query, candidate.content) for candidate in candidates)
        scores = list(model.predict(list(pairs)))
        scored = [
            replace(candidate, rerank_score=float(score), final_score=float(score))
            for candidate, score in zip(candidates, scores, strict=True)
        ]
        scored.sort(key=lambda c: c.final_score, reverse=True)
        return scored[: max(0, top_k)]


def make_reranker() -> Reranker:
    flavor = (os.getenv("TOMMY_RERANKER") or "").strip().lower()
    if flavor == "bge":
        try:
            return BgeReranker()
        except RuntimeError:
            return NullReranker()
    return NullReranker()
