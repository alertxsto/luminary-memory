from __future__ import annotations

import re
from typing import TYPE_CHECKING

from luminary_memory.scope import memory_matches_scope, normalize_scope

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend


def keyword_tokens(text: str) -> set[str]:
    """Words and identifiers used for lexical evidence (not backend ranking)."""
    return {
        token for token in re.findall(r"[^\W_][\w./:+#@=-]*", (text or "").casefold(), re.UNICODE)
        if len(token) >= 2
    }


def term_coverage(query_tokens: set[str], content: str) -> float:
    """Fraction of distinct query terms present in content, in [0, 1]."""
    return len(query_tokens & keyword_tokens(content)) / len(query_tokens) if query_tokens else 0.0



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
    query_terms = keyword_tokens(query)
    legacy_signature = False
    try:
        raw = backend.keyword_search(
            query,
            limit=limit,
            scope=scope,
            include_global=include_global,
        )
    except TypeError:
        import inspect

        try:
            inspect.signature(backend.keyword_search).bind(
                query, limit=limit, scope=scope, include_global=include_global,
            )
        except TypeError:
            pass
        else:
            raise
        # A legacy backend must supply every candidate before validity and
        # tenant filtering; otherwise an expired global top-k can hide a hit.
        legacy_signature = True
        try:
            raw = backend.keyword_search(query, limit=None)
        except TypeError:
            try:
                inspect.signature(backend.keyword_search).bind(query, limit=None)
            except TypeError:
                raw = backend.keyword_search(query, None)
            else:
                raise
    rows = [
        (m, term_coverage(query_terms, m.content), "keyword")
        for m, _backend_score in raw
        if not (needs_local_filter or legacy_signature)
        or memory_matches_scope(m, scope, include_global=include_global, valid_only=True)
    ]
    if needs_local_filter and not rows:
        rows = [
            (m, term_coverage(query_terms, m.content), "keyword")
            for m, _backend_score in _legacy_keyword_scan(backend, query)
            if memory_matches_scope(m, scope, include_global=include_global, valid_only=True)
        ]
    return rows if limit is None else rows[: max(0, int(limit))]
