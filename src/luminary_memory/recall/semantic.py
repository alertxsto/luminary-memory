from __future__ import annotations

import math
from typing import TYPE_CHECKING, Protocol

from luminary_memory.scope import memory_matches_scope, normalize_scope

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend


class _Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


def _legacy_vector_scan(
    backend: MemoryBackend,
    query_vec: list[float],
) -> list[tuple]:
    """Compute a scoped fallback when an old backend hides rows by default."""
    q = [float(value) for value in query_vec]
    q_norm = math.sqrt(sum(value * value for value in q))
    if q_norm <= 0:
        return []
    rows: list[tuple] = []
    for memory in backend.all():
        embedding = getattr(memory, "embedding", None)
        if not embedding or len(embedding) != len(q):
            continue
        values = [float(value) for value in embedding]
        norm = math.sqrt(sum(value * value for value in values))
        if norm <= 0:
            continue
        score = sum(left * right for left, right in zip(values, q)) / (norm * q_norm)
        if math.isfinite(score):
            rows.append((memory, float(score)))
    rows.sort(key=lambda item: (-item[1], -int(getattr(item[0], "id", 0) or 0)))
    return rows


def _cosine(left, right) -> float | None:
    """Cosine similarity between two vectors, or ``None`` when unusable."""
    if not left or not right or len(left) != len(right):
        return None
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    if left_norm <= 0 or right_norm <= 0:
        return None
    score = sum(float(a) * float(b) for a, b in zip(left, right)) / (
        left_norm * right_norm
    )
    return float(score) if math.isfinite(score) else None


def semantic_recall(
    backend: MemoryBackend,
    engine: _Embedder,
    query: str,
    limit: int | None = 10,
    scope: dict | None = None,
    include_global: bool = True,
) -> list[tuple]:
    if limit is not None and int(limit) == 0:
        return []
    expanded = _expand_query(backend, query, scope=scope, include_global=include_global)
    query_vec = engine.embed(expanded)
    # Expansion appends entity names taken from the graph neighbourhood of a
    # shared entity, and those names usually belong to the neighbour memory
    # itself. Letting the expanded text set the score therefore lets a memory
    # supply its own evidence, which overturns the ranking the question itself
    # produced. Expansion stays a candidate-generation device: the question as
    # asked decides how well a candidate answers it.
    support_vec = query_vec if expanded == query else engine.embed(query)
    needs_local_filter = bool(normalize_scope(scope)) or not include_global
    # When the score is going to come from the raw question, the backend's
    # top-k must not be chosen by the expanded one: a memory the question ranks
    # highly would otherwise be cut before it can be scored. Over-fetch a
    # bounded multiple rather than the whole store: scoring every row made
    # recall grow four times slower as the store filled, and doubling the
    # candidate set recovers the same ranking for a quarter of that cost.
    fetch_limit = limit
    if support_vec is not query_vec and limit is not None:
        fetch_limit = max(int(limit) * 2, int(limit) + 16)
    try:
        raw = backend.vector_search(
            query_vec,
            limit=fetch_limit,
            scope=scope,
            include_global=include_global,
        )
    except TypeError:
        # A legacy vector backend may only know about query + limit. Do not
        # let its unscoped top-k hide valid in-scope memories; over-fetch and
        # apply the same scope predicate used by the native backends.
        fallback_limit = None if needs_local_filter else fetch_limit
        try:
            raw = backend.vector_search(query_vec, limit=fallback_limit)
        except TypeError:
            raw = backend.vector_search(query_vec, fallback_limit)
    rows = [
        (m, float(score), "semantic")
        for m, score in raw
        if not needs_local_filter
        or memory_matches_scope(m, scope, include_global=include_global)
    ]
    if needs_local_filter and not rows:
        rows = [
            (m, float(score), "semantic")
            for m, score in _legacy_vector_scan(backend, query_vec)
            if memory_matches_scope(m, scope, include_global=include_global)
        ]
    if support_vec is not query_vec:
        rescored = []
        for memory, score, label in rows:
            raw_score = _cosine(getattr(memory, "embedding", None), support_vec)
            rescored.append((memory, score if raw_score is None else raw_score, label))
        rescored.sort(key=lambda row: (-row[1], -int(getattr(row[0], "id", 0) or 0)))
        rows = rescored
    return rows if limit is None else rows[: max(0, int(limit))]


def _expand_query(
    backend: MemoryBackend,
    query: str,
    max_extra: int = 8,
    scope: dict | None = None,
    include_global: bool = True,
) -> str:
    """Expand a short query with related entity names from the graph.

    A short query like "deploy?" produces a weak embedding. Appending entity
    names that co-occur with the query's entities gives the semantic search
    more signal, so relevant memories rank higher.

    When the graph yields nothing, fall back to content-aware expansion: if the
    query overlaps a high-importance memory, append a few distinctive content
    tokens so that memory can surface even when the query wording differs.
    Both expansions are best-effort and keep the original query tokens.

    Keeping the original tokens does not bound the result: expansion can
    overturn the original ranking when a neighbour memory shares only a generic
    entity with the query. That is an open defect (see docs/recall.md); do not
    read this helper as ranking-safe.
    """
    words = [w for w in (query or "").lower().split() if len(w) > 2]
    if not words:
        return query

    expanded = _expand_with_entities(backend, query, words, max_extra, scope, include_global)
    if expanded != query:
        return expanded
    return _expand_with_rules(backend, query, words, scope, include_global)


def _expand_with_entities(
    backend: MemoryBackend,
    query: str,
    words: list[str],
    max_extra: int,
    scope: dict | None = None,
    include_global: bool = True,
) -> str:
    try:
        from luminary_memory.recall.graph import _exec, _query_entities

        qents = _query_entities(query or "")
        if not qents:
            return query
        ph = ",".join("?" for _ in qents)
        rows = _exec(
            backend,
            f"SELECT id FROM entities WHERE name IN ({ph}) LIMIT 10",
            tuple(qents),
        ).fetchall()
        start_ids = {int(r[0]) for r in rows}
        if not start_ids:
            return query
        sid_ph = ",".join("?" for _ in start_ids)
        from luminary_memory.scope import scope_sql

        scope_where, scope_params = scope_sql(scope, alias="m", include_global=include_global)
        rel_rows = _exec(
            backend,
            f"SELECT DISTINCT t.name FROM relations r "
            f"JOIN entities s ON s.id = r.source_id "
            f"JOIN entities t ON t.id = r.target_id "
            f"JOIN memories m ON m.id = r.memory_id "
            f"WHERE s.id IN ({sid_ph}) AND t.name NOT IN ({ph}) AND {scope_where} "
            f"ORDER BY r.weight DESC LIMIT ?",
            (*start_ids, *qents, *scope_params, max_extra),
        ).fetchall()
        extra = [str(r[0]) for r in rel_rows if str(r[0]) not in words]
        if not extra:
            return query
        return f"{query} {' '.join(extra)}"
    except Exception:  # noqa: BLE001 -- expansion is best-effort
        return query


def _expand_with_rules(
    backend: MemoryBackend,
    query: str,
    words: list[str],
    scope: dict | None = None,
    include_global: bool = True,
) -> str:
    """Append up to two content tokens from an important memory when topics overlap.

    Looks at high-importance memories via the lean backend scan and picks the
    first memory that shares a topic token with the query, appending one or two
    content tokens that are not already in the query. Lossless: the original
    tokens stay in the query.
    """
    try:
        top_by = getattr(backend, "top_by_importance", None)
        if top_by is None:
            return query
        try:
            rules = top_by(
                top_n=8,
                min_importance=0.8,
                scope=scope,
                include_global=include_global,
            )
        except TypeError:
            # The old signature has no scope parameters. Scan/filter locally
            # instead of letting another tenant's durable rule influence the
            # query expansion.
            rules = [
                memory
                for memory in backend.all()
                if float(getattr(memory, "importance", 0.0) or 0.0) >= 0.8
                and memory_matches_scope(
                    memory,
                    scope,
                    include_global=include_global,
                )
            ]
            rules.sort(
                key=lambda memory: (
                    -float(getattr(memory, "importance", 0.0) or 0.0),
                    -int(getattr(memory, "access_count", 0) or 0),
                )
            )
            rules = rules[:8]
        q_set = set(words)
        for rule in rules:
            r_words = [w for w in str(getattr(rule, "content", "") or "").lower().split() if len(w) > 2]
            if not r_words:
                continue
            r_set = set(r_words)
            if not (r_set & q_set):
                continue
            extra = [w for w in r_words if w not in q_set][:2]
            if extra:
                return f"{query} {' '.join(extra)}"
        return query
    except Exception:  # noqa: BLE001 -- expansion is best-effort
        return query
