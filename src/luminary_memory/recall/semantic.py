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
    """
    words = [w for w in (query or "").lower().split() if len(w) > 2]
    if not words:
        return query
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
