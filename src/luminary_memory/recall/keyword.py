from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend


def keyword_recall(
    backend: MemoryBackend,
    query: str,
    limit: int | None = 10,
    scope: dict | None = None,
    include_global: bool = True,
) -> list[tuple]:
    try:
        raw = backend.keyword_search(
            query,
            limit=limit,
            scope=scope,
            include_global=include_global,
        )
    except TypeError:
        raw = backend.keyword_search(query, limit=limit)
    return [(m, float(score), "keyword") for m, score in raw]
