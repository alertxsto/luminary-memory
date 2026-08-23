from __future__ import annotations

import re
from typing import TYPE_CHECKING

from luminary_memory.scope import memory_matches_scope, normalize_scope

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend


def _legacy_keyword_scan(backend: MemoryBackend, query: str) -> list[tuple]:
    """Recover candidates from legacy backends whose unscoped default is global-only."""
    terms = [term.casefold() for term in re.findall(r"\w+", query or "") if term]
    if not terms:
        return []
    rows: list[tuple] = []
    for memory in backend.all():
        content = str(getattr(memory, "content", "") or "").casefold()
        matched = sum(term in content for term in terms)
        if matched:
            score = matched / len(terms)
            rows.append((memory, float(score)))
    rows.sort(key=lambda item: (-item[1], -int(getattr(item[0], "id", 0) or 0)))
    return rows


def keyword_recall(
    backend: MemoryBackend,
    query: str,
    limit: int | None = 10,
    scope: dict | None = None,
    include_global: bool = True,
) -> list[tuple]:
    if limit is not None and int(limit) == 0:
        return []
    needs_local_filter = bool(normalize_scope(scope)) or not include_global
    try:
        raw = backend.keyword_search(
            query,
            limit=limit,
            scope=scope,
            include_global=include_global,
        )
    except TypeError:
        # Keep compatibility with pre-scope backends without allowing their
        # global top-k to crowd out the requested tenant's candidates. Fetch
        # the complete legacy result set, filter locally, then apply limit.
        fallback_limit = None if needs_local_filter else limit
        try:
            raw = backend.keyword_search(query, limit=fallback_limit)
        except TypeError:
            raw = backend.keyword_search(query, fallback_limit)
    rows = [
        (m, float(score), "keyword")
        for m, score in raw
        if not needs_local_filter
        or memory_matches_scope(m, scope, include_global=include_global)
    ]
    if needs_local_filter and not rows:
        rows = [
            (m, float(score), "keyword")
            for m, score in _legacy_keyword_scan(backend, query)
            if memory_matches_scope(m, scope, include_global=include_global)
        ]
    return rows if limit is None else rows[: max(0, int(limit))]
