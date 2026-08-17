from __future__ import annotations

import json
from typing import Any

from luminary_memory.backends.base import MemoryBackend
from luminary_memory.types import Memory


class PGVectorBackend(MemoryBackend):
    def __init__(
        self,
        dsn: str = "postgresql://localhost/luminary_memory",
        embedding_dim: int = 384,
    ):
        import psycopg

        self.dsn = dsn
        self.embedding_dim = int(embedding_dim)
        self._psycopg = psycopg
        self.conn = psycopg.connect(dsn)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS memories (
                id              SERIAL PRIMARY KEY,
                content         TEXT NOT NULL,
                metadata        JSONB NOT NULL DEFAULT '{{}}',
                source          TEXT,
                tags            JSONB NOT NULL DEFAULT '[]',
                importance      DOUBLE PRECISION NOT NULL DEFAULT 0.5,
                ttl_seconds     INTEGER,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_accessed_at TIMESTAMPTZ,
                access_count    INTEGER NOT NULL DEFAULT 0,
                embedding       vector({self.embedding_dim})
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS entities (
                id   SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL DEFAULT 'generic'
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS relations (
                id            SERIAL PRIMARY KEY,
                source_id     INTEGER NOT NULL REFERENCES entities(id),
                target_id     INTEGER NOT NULL REFERENCES entities(id),
                relation_type TEXT NOT NULL DEFAULT 'cooccur',
                weight        DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                memory_id     INTEGER REFERENCES memories(id)
            )
            """
        )
        self.conn.commit()

    def _row_to_memory(self, row: tuple[Any, ...] | dict[str, Any]) -> Memory:
        if isinstance(row, dict):
            d: dict[str, Any] = row
            emb = d.get("embedding")
        else:
            cols = [
                "id", "content", "metadata", "source", "tags", "importance",
                "ttl_seconds", "created_at", "updated_at", "last_accessed_at",
                "access_count", "embedding",
            ]
            d = dict(zip(cols, row))
            emb = d.get("embedding")
        if isinstance(emb, str):
            try:
                emb = json.loads(emb)
            except json.JSONDecodeError:
                emb = None
        return Memory(
            id=int(d["id"]) if d.get("id") is not None else None,
            content=str(d.get("content") or ""),
            metadata=d.get("metadata") if isinstance(d.get("metadata"), dict) else json.loads(d.get("metadata") or "{}") if d.get("metadata") else {},
            source=d.get("source"),
            tags=d.get("tags") if isinstance(d.get("tags"), list) else json.loads(d.get("tags") or "[]") if d.get("tags") else [],
            importance=float(d.get("importance") or 0.5),
            ttl_seconds=d.get("ttl_seconds"),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            last_accessed_at=str(d["last_accessed_at"]) if d.get("last_accessed_at") else None,
            access_count=int(d.get("access_count") or 0),
            embedding=list(emb) if isinstance(emb, (list, tuple)) else None,
        )

    def add(self, m: Memory) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO memories (content, metadata, source, tags, importance,
                                  ttl_seconds, created_at, updated_at,
                                  last_accessed_at, access_count, embedding)
            VALUES (%s, %s::jsonb, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                m.content,
                json.dumps(m.metadata),
                m.source,
                json.dumps(m.tags),
                float(m.importance),
                m.ttl_seconds,
                m.created_at,
                m.updated_at,
                m.last_accessed_at,
                int(m.access_count),
                m.embedding,
            ),
        )
        row = cur.fetchone()
        self.conn.commit()
        return int(row[0]) if row else 0

    def get(self, id: int) -> Memory | None:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM memories WHERE id = %s", (id,))
        row = cur.fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            return self._row_to_memory(row)
        return self._row_to_memory(row)

    def update(self, m: Memory) -> None:
        if m.id is None:
            raise ValueError("cannot update a memory without an id")
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE memories SET content=%s, metadata=%s::jsonb, source=%s, tags=%s::jsonb,
                                importance=%s, ttl_seconds=%s, updated_at=%s,
                                last_accessed_at=%s, access_count=%s, embedding=%s
            WHERE id=%s
            """,
            (
                m.content,
                json.dumps(m.metadata),
                m.source,
                json.dumps(m.tags),
                float(m.importance),
                m.ttl_seconds,
                m.updated_at,
                m.last_accessed_at,
                int(m.access_count),
                m.embedding,
                m.id,
            ),
        )
        self.conn.commit()

    def delete(self, id: int) -> None:
        cur = self.conn.cursor()
        # Relations reference memories via FK; delete them first (manual cascade).
        cur.execute("DELETE FROM relations WHERE memory_id = %s", (id,))
        cur.execute("DELETE FROM memories WHERE id = %s", (id,))
        self.conn.commit()

    def all(self) -> list[Memory]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM memories ORDER BY id")
        rows = cur.fetchall()
        return [self._row_to_memory(r) for r in rows]

    def keyword_search(self, query: str, limit: int = 10) -> list[tuple[Memory, float]]:
        escaped = query.replace("%", r"\%").replace("_", r"\_")
        q = f"%{escaped}%"
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM memories WHERE content ILIKE %s OR tags::text ILIKE %s LIMIT %s",
            (q, q, int(limit)),
        )
        rows = cur.fetchall()
        return [(self._row_to_memory(r), 1.0) for r in rows]

    def vector_search(self, vec: list[float], limit: int = 10) -> list[tuple[Memory, float]]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT *, embedding <=> %s::vector AS distance FROM memories "
            "WHERE embedding IS NOT NULL ORDER BY distance LIMIT %s",
            (vec, int(limit)),
        )
        rows = cur.fetchall()
        results: list[tuple[Memory, float]] = []
        for r in rows:
            if isinstance(r, dict):
                dist = float(r.get("distance") or 0.0)
            elif isinstance(r, (list, tuple)) and len(r) >= 13:
                dist = float(r[-1] or 0.0)
            else:
                dist = 0.0
            results.append((self._row_to_memory(r), 1.0 - dist))
        return results

    def count(self) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM memories")
        row = cur.fetchone()
        if row is None:
            return 0
        return int(row[0] if isinstance(row, (list, tuple)) else row.get("count", 0))

    def close(self) -> None:
        try:
            self.conn.close()
        except (AttributeError, OSError, RuntimeError):
            pass
