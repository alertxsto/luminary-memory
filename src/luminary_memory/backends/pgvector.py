from __future__ import annotations

import json
import logging
from typing import Any

from luminary_memory.backends.base import MemoryBackend
from luminary_memory.types import Memory

logger = logging.getLogger(__name__)


def _json_load(value, default):
    """Safely parse a JSON column value; fall back to *default* on failure."""
    if value is None or value == "":
        return default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


class PGVectorBackend(MemoryBackend):
    def __init__(
        self,
        dsn: str = "postgresql://localhost/luminary_memory",
        embedding_dim: int = 384,
        hnsw: bool | None = None,
        hnsw_m: int | None = None,
        hnsw_ef_construction: int | None = None,
    ):
        import psycopg

        self.dsn = dsn
        self.embedding_dim = int(embedding_dim)
        self._psycopg = psycopg
        self.conn = psycopg.connect(dsn)
        self._ensure_schema()
        # Optional HNSW index (feature-flagged, never hard-fails).
        from luminary_memory.config import Settings as _Settings

        _s = _Settings()
        do_hnsw = bool(hnsw if hnsw is not None else _s.pg_hnsw_index)
        if do_hnsw:
            self.build_index(
                m=int(hnsw_m if hnsw_m is not None else _s.pg_hnsw_m),
                ef_construction=int(
                    hnsw_ef_construction if hnsw_ef_construction is not None else _s.pg_hnsw_ef_construction
                ),
            )

    def build_index(self, m: int = 16, ef_construction: int = 64) -> None:
        try:
            cur = self.conn.cursor()
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS memories_embedding_hnsw "
                f"ON memories USING hnsw (embedding vector_cosine_ops) "
                f"WITH (m = {int(m)}, ef_construction = {int(ef_construction)})"
            )
            self.conn.commit()
        except Exception:
            logger.warning("HNSW index creation failed (non-fatal)", exc_info=True)
            try:
                self.conn.rollback()
            except Exception:  # noqa: BLE001, S110
                pass

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
            metadata=_json_load(d.get("metadata"), {}),
            source=d.get("source"),
            tags=_json_load(d.get("tags"), []),
            importance=float(d.get("importance") or 0.5),
            ttl_seconds=d.get("ttl_seconds"),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            last_accessed_at=str(d["last_accessed_at"]) if d.get("last_accessed_at") else None,
            access_count=int(d.get("access_count") or 0),
            embedding=list(emb) if isinstance(emb, (list, tuple)) else None,
            snippet=None,
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

    def add_many(self, memories: list[Memory]) -> list[int]:
        if not memories:
            return []
        cur = self.conn.cursor()
        ids: list[int] = []
        for m in memories:
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
            ids.append(int(row[0]) if row and row[0] is not None else 0)
        self.conn.commit()
        return ids

    def recent(self, limit: int | None = 100, offset: int = 0) -> list[Memory]:
        """Most-recent-first pagination at the SQL level (None = unlimited)."""
        cur = self.conn.cursor()
        o = max(0, int(offset))
        if limit is None or int(limit) == 0:
            cur.execute(
                "SELECT * FROM memories ORDER BY created_at DESC, id DESC OFFSET %s",
                (o,),
            )
        else:
            cur.execute(
                "SELECT * FROM memories ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
                (max(0, int(limit)), o),
            )
        rows = cur.fetchall()
        return [self._row_to_memory(r) for r in rows]

    def keyword_search(self, query: str, limit: int | None = 10) -> list[tuple[Memory, float]]:
        escaped = query.replace("%", r"\%").replace("_", r"\_")
        q = f"%{escaped}%"
        cur = self.conn.cursor()
        if limit is None:
            cur.execute(
                "SELECT * FROM memories WHERE content ILIKE %s OR tags::text ILIKE %s",
                (q, q),
            )
        else:
            cur.execute(
                "SELECT * FROM memories WHERE content ILIKE %s OR tags::text ILIKE %s LIMIT %s",
                (q, q, int(limit)),
            )
        rows = cur.fetchall()
        return [(self._row_to_memory(r), 1.0) for r in rows]

    def vector_search(self, vec: list[float], limit: int | None = 10) -> list[tuple[Memory, float]]:
        cur = self.conn.cursor()
        if limit is None:
            cur.execute(
                "SELECT *, embedding <=> %s::vector AS distance FROM memories "
                "WHERE embedding IS NOT NULL ORDER BY distance",
                (vec,),
            )
        else:
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

    def by_tags(self, tags: list[str]) -> set[int]:
        if not tags:
            return set()
        cur = self.conn.cursor()
        # JSONB tags @> check per tag; fallback to python filter when driver absent.
        try:
            import json as _json

            wanted = set(tags)
            cur.execute("SELECT id, tags FROM memories")
            ids: set[int] = set()
            for row in cur.fetchall():
                d = row if isinstance(row, dict) else {}
                if not isinstance(row, dict):
                    # tuple path: map via description
                    cols = [desc[0] for desc in (cur.description or [])]
                    d = dict(zip(cols, row)) if cols else {}
                raw = d.get("tags")
                if isinstance(raw, list):
                    tlist = raw
                else:
                    try:
                        tlist = _json.loads(raw) if isinstance(raw, str) else list(raw or [])
                    except Exception:  # noqa: BLE001
                        tlist = []
                if wanted & set(tlist):
                    ids.add(int(d.get("id") or row[0]))
            return ids
        except Exception:  # noqa: BLE001
            return set()

    def close(self) -> None:
        try:
            self.conn.close()
        except (AttributeError, OSError, RuntimeError):
            pass
