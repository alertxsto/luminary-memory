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
    """Return unique tags then content tokens in their original salience order."""
    entities: dict[str, None] = {}
    for tag in getattr(m, "tags", []) or []:
        name = str(tag).casefold().strip()
        if name:
            entities[name] = None
    content = getattr(m, "content", "") or ""
    for token in _TOKEN_RE.findall(content.casefold()):
        # Keep the filter structural rather than linguistic: no stopword list
        # should privilege one language or silently discard another script.
        if any(character.isalpha() for character in token):
            entities[token] = None
    return list(entities)


# Bound indexing work per memory. A star connects every selected entity to
# the first (most salient) one with O(k) edges rather than O(k²) pairs.
MAX_RELATIONS_PER_MEMORY = 16


def index_memory_entities(backend, memory) -> None:
    if getattr(memory, "id", None) is None:
        return
    # Clear old edges even when the updated content has no extractable
    # entities. Otherwise a rename/removal leaves stale graph evidence that
    # can keep an obsolete memory in recall.
    _exec(backend, "DELETE FROM relations WHERE memory_id = ?", (memory.id,))
    ents = extract_entities(memory)[:MAX_RELATIONS_PER_MEMORY + 1]
    if len(ents) < 2:
        backend.conn.commit()
        return
    placeholders = ",".join("(?)" for _ in ents)
    if _is_pg(backend):
        _exec(
            backend,
            f"INSERT INTO entities (name) VALUES {placeholders} ON CONFLICT (name) DO NOTHING",
            tuple(ents),
        )
    else:
        _exec(backend, f"INSERT OR IGNORE INTO entities (name) VALUES {placeholders}", tuple(ents))
    names = ",".join("?" for _ in ents)
    ids = {
        name: int(entity_id)
        for entity_id, name in _exec(
            backend, f"SELECT id, name FROM entities WHERE name IN ({names})", tuple(ents)
        ).fetchall()
    }
    anchor = ids[ents[0]]
    for name in ents[1:]:
        target_id = ids[name]
        for source_id, destination_id in ((anchor, target_id), (target_id, anchor)):
            _exec(
                backend,
                "INSERT INTO relations (source_id, target_id, relation_type, weight, memory_id) "
                "VALUES (?, ?, 'cooccur', 1.0, ?)",
                (source_id, destination_id, memory.id),
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
        valid_only=True,
        dialect="postgres" if _is_pg(backend) else "sqlite",
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
