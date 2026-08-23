from __future__ import annotations

import re
from typing import TYPE_CHECKING

from luminary_memory.scope import scope_sql

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend

_TOKEN_RE = re.compile(r"[^\W_]{3,}", re.UNICODE)


def _is_pg(backend) -> bool:
    # Avoid a hard import cycle: pgvector backend is not SQLiteBackend.
    from luminary_memory.backends.sqlite import SQLiteBackend

    return not isinstance(backend, SQLiteBackend)


def _exec(backend, sqlite_sql: str, params: tuple = ()):
    """Run SQL against either backend dialect.

    SQLite uses ``?`` placeholders via ``conn.execute``; pgvector uses
    ``%s`` placeholders via a cursor. The two SQL strings differ only in
    placeholder style, so we pass the SQLite form and rewrite ``?`` -> ``%s``
    for the postgres path.
    """
    if _is_pg(backend):
        cur = backend.conn.cursor()
        cur.execute(sqlite_sql.replace("?", "%s"), params)
        return cur
    return backend.conn.execute(sqlite_sql, params)


def extract_entities(m) -> list[str]:
    entities: set[str] = set()
    for tag in getattr(m, "tags", []) or []:
        if tag:
            entities.add(tag.casefold().strip())
    content = getattr(m, "content", "") or ""
    for token in _TOKEN_RE.findall(content.casefold()):
        # Keep the filter structural rather than linguistic: no stopword list
        # should privilege one language or silently discard another script.
        if any(character.isalpha() for character in token):
            entities.add(token)
    return sorted(entities)


def _entity_id(backend, name: str) -> int:
    if _is_pg(backend):
        _exec(
            backend,
            "INSERT INTO entities (name) VALUES (?) ON CONFLICT (name) DO NOTHING",
            (name,),
        )
    else:
        _exec(backend, "INSERT OR IGNORE INTO entities (name) VALUES (?)", (name,))
    row = _exec(backend, "SELECT id FROM entities WHERE name = ?", (name,)).fetchone()
    return int(row[0])


# Cap on co-occurrence edges per memory. Without a cap, a memory with k
# entities creates k*(k-1) directed edges — a memory with 8 entities yields
# 56 relations, and 5k memories explode into ~280k rows that dominate both
# storage and graph-recall latency. Capping keeps the graph sparse while
# retaining the strongest connections (earliest entities are the most
# salient in the source text).
MAX_RELATIONS_PER_MEMORY = 8


def index_memory_entities(backend, memory) -> None:
    if getattr(memory, "id", None) is None:
        return
    # Clear old edges even when the updated content has no extractable
    # entities. Otherwise a rename/removal leaves stale graph evidence that
    # can keep an obsolete memory in recall.
    _exec(backend, "DELETE FROM relations WHERE memory_id = ?", (memory.id,))
    ents = extract_entities(memory)
    if not ents:
        backend.conn.commit()
        return
    ids = [_entity_id(backend, e) for e in ents]
    # Generate pairs in salience order (first entities are most salient),
    # then cap the total so dense memories don't explode the graph.
    pairs: list[tuple[int, int]] = []
    for i, source_id in enumerate(ids):
        for target_id in ids[i + 1:]:
            pairs.append((source_id, target_id))
            if len(pairs) >= MAX_RELATIONS_PER_MEMORY:
                break
        if len(pairs) >= MAX_RELATIONS_PER_MEMORY:
            break
    for source_id, target_id in pairs:
        _exec(
            backend,
            "INSERT INTO relations (source_id, target_id, relation_type, weight, memory_id) "
            "VALUES (?, ?, 'cooccur', 1.0, ?)",
            (source_id, target_id, memory.id),
        )
        _exec(
            backend,
            "INSERT INTO relations (source_id, target_id, relation_type, weight, memory_id) "
            "VALUES (?, ?, 'cooccur', 1.0, ?)",
            (target_id, source_id, memory.id),
        )
    backend.conn.commit()


def _query_entities(query: str) -> set[str]:
    ents: set[str] = set()
    for token in _TOKEN_RE.findall((query or "").casefold()):
        if any(character.isalpha() for character in token):
            ents.add(token)
    return ents


def graph_recall(
    backend: MemoryBackend,
    query: str,
    limit: int | None = 10,
    scope: dict | None = None,
    include_global: bool = True,
) -> list[tuple]:
    query_ents = _query_entities(query)
    if not query_ents:
        return []
    placeholders = ",".join("?" for _ in query_ents)
    rows = _exec(
        backend,
        f"SELECT id FROM entities WHERE name IN ({placeholders})",
        tuple(query_ents),
    ).fetchall()
    start_ids = {int(r[0]) for r in rows}
    if not start_ids:
        return []

    sid_ph = ",".join("?" for _ in start_ids)
    # Aggregate relation scores in SQL instead of fetching every row into
    # Python (a dense entity graph can produce hundreds of thousands of
    # relation rows; summing them in the database is orders of magnitude
    # faster and yields identical scores).
    scope_where, scope_params = scope_sql(
        scope,
        alias="m",
        include_global=include_global,
    )
    rel_rows = _exec(
        backend,
        f"SELECT memory_id, SUM(weight) AS score, COUNT(*) AS cnt "
        f"FROM relations r JOIN memories m ON m.id = r.memory_id "
        f"WHERE r.source_id IN ({sid_ph}) AND {scope_where} "
        f"GROUP BY memory_id",
        tuple(start_ids) + tuple(scope_params),
    ).fetchall()
    rel_scores: dict[int, float] = {}
    rel_counts: dict[int, int] = {}
    for memory_id, weight_sum, cnt in rel_rows:
        rel_scores[int(memory_id)] = rel_scores.get(int(memory_id), 0.0) + float(weight_sum or 1.0)
        rel_counts[int(memory_id)] = rel_counts.get(int(memory_id), 0) + int(cnt)

    direct_ids: set[int] = set()
    eid_ph = ",".join("?" for _ in start_ids)
    for mid_row in _exec(
        backend,
        f"SELECT DISTINCT r.memory_id FROM relations r "
        f"JOIN memories m ON m.id = r.memory_id "
        f"WHERE (r.source_id IN ({eid_ph}) OR r.target_id IN ({eid_ph})) "
        f"AND {scope_where}",
        tuple(start_ids) + tuple(start_ids) + tuple(scope_params),
    ).fetchall():
        direct_ids.add(int(mid_row[0]))
    for mid in direct_ids:
        rel_scores.setdefault(mid, 0.5)

    # Batch-fetch all candidate memories in one query (avoids N+1
    # per-id SELECTs, which dominates at scale).
    scored: list[tuple] = []
    if rel_scores:
        mid_ph = ",".join("?" for _ in rel_scores)
        mem_rows = _exec(
            backend,
            f"SELECT * FROM memories m WHERE m.id IN ({mid_ph}) AND {scope_where}",
            tuple(rel_scores.keys()) + tuple(scope_params),
        ).fetchall()
        def _row_id(row) -> int | None:
            if isinstance(row, dict):
                value = row.get("id")
            else:
                try:
                    value = row["id"]
                except (IndexError, KeyError, TypeError):
                    # psycopg's default tuple rows have the table's primary
                    # key first (SELECT * FROM memories).
                    value = row[0] if row else None
            try:
                return int(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        mem_by_id = {
            memory_id: row
            for row in mem_rows
            if (memory_id := _row_id(row)) is not None
        }
        row_to_mem = getattr(backend, "_row_to_memory", None)
        for mid, score in rel_scores.items():
            row = mem_by_id.get(int(mid))
            if row is None:
                continue
            if row_to_mem is not None:
                mem = row_to_mem(row)
            else:
                mem = backend.get(int(mid))  # fallback: per-id fetch
            if mem is not None:
                scored.append((mem, float(score), "graph"))
    scored.sort(key=lambda x: -x[1])
    return scored if limit is None else scored[:limit]
