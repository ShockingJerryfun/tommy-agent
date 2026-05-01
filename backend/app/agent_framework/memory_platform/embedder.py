"""Abstract API embedding interface + production/test implementations.

Decisions from blueprint §13:

- Embedding model: abstract interface for an API-based embedding model.
- The interface MUST allow swapping the provider without touching the
  retriever or repo code. ``OpenAIEmbedder`` is the production default;
  ``EchoEmbedder`` is deterministic for tests; ``NullEmbedder`` makes the
  vector path a graceful no-op when no provider is configured.

The repo's ``embedding`` column is ``vector(1536)``. Every concrete
embedder must therefore project to 1536 dims (or refuse). The factory
honors three env vars:

- ``TOMMY_EMBEDDING_PROVIDER`` — ``openai`` | ``echo`` | ``null``
  (default: ``openai`` if ``OPENAI_API_KEY`` is set, else ``null``)
- ``TOMMY_EMBEDDING_MODEL`` — provider-specific model id
- ``TOMMY_EMBEDDING_API_KEY`` — overrides ``OPENAI_API_KEY`` if set
"""

from __future__ import annotations

import hashlib
import math
import os
from typing import Any, Protocol

EMBEDDING_DIM = 1536
"""All embeddings are projected to this dim before storage.

Matches the ``vector(1536)`` column type. If a future provider returns a
different dim, wrap it in a projector that pads/truncates to 1536.
"""


class Embedder(Protocol):
    """Pluggable embedding provider."""

    model: str
    dim: int

    def embed(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class NullEmbedder:
    """Returns empty vectors. The retriever skips the vector branch."""

    model = ""
    dim = EMBEDDING_DIM

    def embed(self, text: str) -> list[float]:  # noqa: ARG002 — interface method
        return []

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


class EchoEmbedder:
    """Deterministic synthetic embedder used in tests.

    Hashes the input with SHA-256, expands the hash into a 1536-dim float
    vector by repeating bytes, and L2-normalises. Identical strings get
    identical vectors; substrings stay close in cosine space, which is
    enough for unit-testing the retriever's RRF logic without external
    dependencies.
    """

    model = "echo-1536"
    dim = EMBEDDING_DIM

    def embed(self, text: str) -> list[float]:
        if not text:
            text = "<empty>"
        # Hash deterministically, then expand to 1536 floats in [-1, 1].
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = list(digest)  # 32 bytes
        floats: list[float] = []
        i = 0
        while len(floats) < self.dim:
            byte = seed[i % len(seed)]
            # Map 0..255 -> -1..1
            floats.append((byte / 127.5) - 1.0)
            i += 1
        # L2 normalise to make cosine == dot product.
        norm = math.sqrt(sum(v * v for v in floats)) or 1.0
        return [v / norm for v in floats]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class OpenAIEmbedder:
    """Production embedder backed by an OpenAI-compatible API.

    Uses ``langchain_openai.OpenAIEmbeddings`` (already a project dep) so
    we inherit retries and batching. The model defaults to
    ``text-embedding-3-small`` (1536 dim). If the provider returns a
    different dim, the result is padded/truncated to 1536 to match the
    ``vector(1536)`` column.
    """

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        try:
            from langchain_openai import OpenAIEmbeddings  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover — exercised when dep missing
            raise RuntimeError(
                "langchain_openai is required for OpenAIEmbedder; "
                "install it or set TOMMY_EMBEDDING_PROVIDER=null."
            ) from exc

        kwargs: dict[str, Any] = {"model": model}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAIEmbeddings(**kwargs)
        self.model = model
        self.dim = EMBEDDING_DIM

    @staticmethod
    def _project(values: list[float]) -> list[float]:
        if len(values) == EMBEDDING_DIM:
            return values
        if len(values) > EMBEDDING_DIM:
            return values[:EMBEDDING_DIM]
        return values + [0.0] * (EMBEDDING_DIM - len(values))

    def embed(self, text: str) -> list[float]:
        if not text:
            return []
        result = self._client.embed_query(text)
        return self._project(list(result))

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        results = self._client.embed_documents(texts)
        return [self._project(list(item)) for item in results]


def make_embedder() -> Embedder:
    """Factory honoring the env-var contract documented at the top."""

    provider = (os.getenv("TOMMY_EMBEDDING_PROVIDER") or "").strip().lower()
    api_key = (os.getenv("TOMMY_EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
    base_url = (os.getenv("TOMMY_EMBEDDING_BASE_URL") or "").strip()
    model = (os.getenv("TOMMY_EMBEDDING_MODEL") or "text-embedding-3-small").strip()

    if not provider:
        provider = "openai" if api_key else "null"

    if provider == "null":
        return NullEmbedder()
    if provider == "echo":
        return EchoEmbedder()
    if provider == "openai":
        if not api_key:
            return NullEmbedder()
        try:
            return OpenAIEmbedder(model=model, api_key=api_key, base_url=base_url or None)
        except RuntimeError:
            return NullEmbedder()
    return NullEmbedder()
