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
    limit: int | None = 10,
) -> list[tuple]:
    query_vec = engine.embed(_expand_query(backend, query))
    raw = backend.vector_search(query_vec, limit=limit)
    return [(m, float(score), "semantic") for m, score in raw]


def _expand_query(backend: MemoryBackend, query: str, max_extra: int = 8) -> str:
    """Expand a short query with related entity names from the graph.

    A short query like "deploy?" produces a weak embedding. Appending entity
    names that co-occur with the query's entities gives the semantic search
    more signal, so relevant memories rank higher.

    When the graph yields nothing, fall back to rule-aware expansion: if the
    query touches the topic of a durable rule (high-importance memory), append
    its distinctive keywords so the rule surfaces in semantic recall even when
    the query words differ. Both expansions are best-effort and keep the
    original query tokens, so recall can never get *worse* than baseline.
    """
    words = [w for w in (query or "").lower().split() if len(w) > 2]
    if not words:
        return query

    expanded = _expand_with_entities(backend, query, words, max_extra)
    if expanded != query:
        return expanded
    return _expand_with_rules(backend, query, words)


def _expand_with_entities(backend: MemoryBackend, query: str, words: list[str], max_extra: int) -> str:
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
        rel_rows = _exec(
            backend,
            f"SELECT DISTINCT t.name FROM relations r "
            f"JOIN entities s ON s.id = r.source_id "
            f"JOIN entities t ON t.id = r.target_id "
            f"WHERE s.id IN ({sid_ph}) AND t.name NOT IN ({ph}) "
            f"ORDER BY r.weight DESC LIMIT ?",
            (*start_ids, *qents, max_extra),
        ).fetchall()
        extra = [str(r[0]) for r in rel_rows if str(r[0]) not in words]
        if not extra:
            return query
        return f"{query} {' '.join(extra)}"
    except Exception:  # noqa: BLE001 -- expansion is best-effort
        return query


def _expand_with_rules(backend: MemoryBackend, query: str, words: list[str]) -> str:
    """Append up to 2 keywords from a durable rule whose topic overlaps the query.

    Looks at high-importance memories (rules) via the lean backend scan and
    picks the first rule that shares a topic token with the query, appending a
    keyword or two that are not already in the query. Lossless: the original
    tokens stay in the query.
    """
    try:
        top_by = getattr(backend, "top_by_importance", None)
        if top_by is None:
            return query
        rules = top_by(top_n=8, min_importance=0.8)
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
