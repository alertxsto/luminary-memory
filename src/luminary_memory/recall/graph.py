from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend

_WORD_RE = re.compile(r"[A-Za-z]{" r"3," r"}")
_STOP = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "is",
    "you", "your", "but", "not", "has", "have", "had", "will", "would",
    "can", "could", "should", "about", "into", "over", "under", "between",
    "among", "through", "which", "their", "there", "what", "when", "where",
})


def extract_entities(m) -> list[str]:
    entities: set[str] = set()
    for tag in getattr(m, "tags", []) or []:
        if tag:
            entities.add(tag.lower().strip())
    for word in _WORD_RE.findall(m.content.lower()):
        if word not in _STOP:
            entities.add(word)
    return sorted(entities)


def _entity_id(conn, name: str) -> int:
    conn.execute("INSERT OR IGNORE INTO entities (name) VALUES (?)", (name,))
    row = conn.execute("SELECT id FROM entities WHERE name = ?", (name,)).fetchone()
    return int(row[0])


def index_memory_entities(backend, memory) -> None:
    conn = backend.conn
    ents = extract_entities(memory)
    if not ents:
        return
    ids = [_entity_id(conn, e) for e in ents]
    for i, source_id in enumerate(ids):
        for target_id in ids[i + 1:]:
            conn.execute(
                "INSERT INTO relations (source_id, target_id, relation_type, weight, memory_id) "
                "VALUES (?, ?, 'cooccur', 1.0, ?)",
                (source_id, target_id, memory.id),
            )
            conn.execute(
                "INSERT INTO relations (source_id, target_id, relation_type, weight, memory_id) "
                "VALUES (?, ?, 'cooccur', 1.0, ?)",
                (target_id, source_id, memory.id),
            )
    conn.commit()


def _query_entities(query: str) -> set[str]:
    ents: set[str] = set()
    for w in _WORD_RE.findall(query.lower()):
        if w not in _STOP:
            ents.add(w)
    return ents


def graph_recall(
    backend: MemoryBackend,
    query: str,
    limit: int = 10,
) -> list[tuple]:
    query_ents = _query_entities(query)
    if not query_ents:
        return []
    conn = backend.conn
    placeholders = ",".join("?" for _ in query_ents)
    rows = conn.execute(
        f"SELECT id FROM entities WHERE name IN ({placeholders})",
        list(query_ents),
    ).fetchall()
    start_ids = {int(r[0]) for r in rows}
    if not start_ids:
        return []

    sid_ph = ",".join("?" for _ in start_ids)
    # find memories linked to these entities or neighbors
    rel_rows = conn.execute(
        f"SELECT target_id, weight, memory_id FROM relations WHERE source_id IN ({sid_ph})",
        list(start_ids),
    ).fetchall()
    rel_scores: dict[int, float] = {}
    rel_counts: dict[int, int] = {}
    for target_id, weight, mid in rel_rows:
        rel_scores[mid] = rel_scores.get(mid, 0.0) + float(weight or 1.0)
        rel_counts[mid] = rel_counts.get(mid, 0) + 1
    # also memories that directly contain any query entity (no relation needed)
    # resolve memory ids that own any query entity
    direct_ids: set[int] = set()
    for eid in start_ids:
        for mid_row in conn.execute(
            "SELECT memory_id FROM relations WHERE source_id = ? OR target_id = ?",
            (eid, eid),
        ).fetchall():
            direct_ids.add(int(mid_row[0]))
    # merge scores
    for mid in direct_ids:
        rel_scores.setdefault(mid, 0.5)

    scored: list[tuple] = []
    for mid, score in rel_scores.items():
        mem = backend.get(mid)
        if mem is not None:
            scored.append((mem, float(score), "graph"))
    scored.sort(key=lambda x: -x[1])
    return scored[:limit]
