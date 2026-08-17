from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend


def keyword_recall(
    backend: MemoryBackend,
    query: str,
    limit: int | None = 10,
) -> list[tuple]:
    raw = backend.keyword_search(query, limit=limit)
    return [(m, float(score), "keyword") for m, score in raw]
