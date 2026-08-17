from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend


class _Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


def semantic_recall(
    backend: MemoryBackend,
    engine: _Embedder,
    query: str,
    limit: int = 10,
) -> list[tuple]:
    query_vec = engine.embed(query)
    raw = backend.vector_search(query_vec, limit=limit)
    return [(m, float(score), "semantic") for m, score in raw]
