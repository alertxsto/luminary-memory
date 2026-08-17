from __future__ import annotations
import json
import sqlite3

import numpy as np

from luminary_memory.backends.base import MemoryBackend
from luminary_memory.schema import init_schema
from luminary_memory.types import Memory


class SQLiteBackend(MemoryBackend):
    def __init__(self, db_path: str = "luminary_memory.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        init_schema(self.conn)

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        m = Memory(
            id=row["id"],
            content=row["content"],
            metadata=json.loads(row["metadata"] or "{}"),
            source=row["source"],
            tags=json.loads(row["tags"] or "[]"),
            importance=row["importance"],
            ttl_seconds=row["ttl_seconds"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_accessed_at=row["last_accessed_at"],
            access_count=row["access_count"],
        )
        emb = row["embedding"]
        if emb is not None:
            m.embedding = np.frombuffer(emb, dtype=np.float32).tolist()
        return m

    @staticmethod
    def _encode_embedding(vec: list[float] | None) -> bytes | None:
        if vec is None:
            return None
        return np.asarray(vec, dtype=np.float32).tobytes()

    def add(self, m: Memory) -> int:
        cur = self.conn.execute(
            "INSERT INTO memories (content, metadata, source, tags, importance, "
            "ttl_seconds, created_at, updated_at, last_accessed_at, access_count, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                m.content,
                json.dumps(m.metadata),
                m.source,
                json.dumps(m.tags),
                m.importance,
                m.ttl_seconds,
                m.created_at,
                m.updated_at,
                m.last_accessed_at,
                m.access_count,
                self._encode_embedding(m.embedding),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get(self, id: int) -> Memory | None:
        row = self.conn.execute("SELECT * FROM memories WHERE id = ?", (id,)).fetchone()
        return self._row_to_memory(row) if row else None

    def update(self, m: Memory) -> None:
        if m.id is None:
            raise ValueError("cannot update a memory without an id")
        self.conn.execute(
            "UPDATE memories SET content=?, metadata=?, source=?, tags=?, importance=?, "
            "ttl_seconds=?, updated_at=?, last_accessed_at=?, access_count=?, embedding=? "
            "WHERE id=?",
            (
                m.content,
                json.dumps(m.metadata),
                m.source,
                json.dumps(m.tags),
                m.importance,
                m.ttl_seconds,
                m.updated_at,
                m.last_accessed_at,
                m.access_count,
                self._encode_embedding(m.embedding),
                m.id,
            ),
        )
        self.conn.commit()

    def delete(self, id: int) -> None:
        self.conn.execute("DELETE FROM memories WHERE id = ?", (id,))
        self.conn.commit()

    def all(self) -> list[Memory]:
        rows = self.conn.execute("SELECT * FROM memories ORDER BY id").fetchall()
        return [self._row_to_memory(r) for r in rows]

    def keyword_search(self, query: str, limit: int = 10) -> list[tuple[Memory, float]]:
        safe = query.replace('"', ' ')
        rows = self.conn.execute(
            "SELECT m.*, bm25(memories_fts) AS rank "
            "FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid "
            "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
            (safe, limit),
        ).fetchall()
        return [(self._row_to_memory(r), -float(r["rank"])) for r in rows]

    def vector_search(self, vec: list[float], limit: int = 10) -> list[tuple[Memory, float]]:
        q = np.asarray(vec, dtype=np.float32)
        qn = float(np.linalg.norm(q))
        results: list[tuple[Memory, float]] = []
        for m in self.all():
            if m.embedding is None:
                continue
            v = np.asarray(m.embedding, dtype=np.float32)
            vn = float(np.linalg.norm(v))
            sim = 0.0 if (qn == 0 or vn == 0) else float(np.dot(q, v) / (qn * vn))
            results.append((m, sim))
        results.sort(key=lambda x: -x[1])
        return results[:limit]

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        return int(row[0])

    def close(self) -> None:
        self.conn.close()
