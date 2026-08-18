from __future__ import annotations

import json
import logging
import sqlite3
import threading

import numpy as np

from luminary_memory.backends.base import MemoryBackend
from luminary_memory.schema import init_schema
from luminary_memory.types import Memory

logger = logging.getLogger(__name__)

# FTS5 special characters that can alter query semantics (syntax injection).
_FTS5_SPECIAL = ('"', "*", ":", "^", "(", ")", "{", "}", "[", "]", "-", "+", "~", "NEAR", "AND", "OR", "NOT")


def _sanitize_fts_query(query: str) -> str:
    """Strip FTS5 query syntax so user input is treated as plain terms.

    Without this, characters like ``*``, ``NEAR``, or quoted phrases can
    change the query into something the user did not intend (and can raise
    syntax errors on malformed input). We keep only word characters, which
    is the safest interpretation for plain keyword search.
    """
    import re

    cleaned = re.sub(r"[^\w\s]", " ", query)
    cleaned = " ".join(cleaned.split())
    return cleaned or '" "'


class SQLiteBackend(MemoryBackend):
    def __init__(self, db_path: str = "luminary_memory.db"):
        self.db_path = db_path
        self._local = threading.local()
        # Prime the main-thread connection so single-threaded callers keep
        # working exactly as before.
        self._get_conn()

    def _get_conn(self) -> sqlite3.Connection:
        """Return a connection owned by the calling thread.

        SQLite connections are bound to the thread that created them. The
        provider runs prefetch recall on a background thread while the main
        thread ingests/retains, so a single shared connection raises
        ``ProgrammingError`` when touched from the other thread. Thread-local
        connections fix that without any cross-thread locking.
        """
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            init_schema(conn)
            self._local.conn = conn
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._get_conn()

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

    def get_many(self, ids: list[int]) -> dict[int, Memory]:
        """Batch get — one SELECT for many ids instead of N per-id queries."""
        if not ids:
            return {}
        ph = ",".join("?" for _ in ids)
        rows = self.conn.execute(
            f"SELECT * FROM memories WHERE id IN ({ph})", ids
        ).fetchall()
        return {int(r["id"]): self._row_to_memory(r) for r in rows}

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
        # Relations reference memories via FK; delete them first (manual cascade).
        self.conn.execute("DELETE FROM relations WHERE memory_id = ?", (id,))
        self.conn.execute("DELETE FROM memories WHERE id = ?", (id,))
        self.conn.commit()

    def delete_many(self, ids: list[int]) -> None:
        """Batch delete (relations + memories) in two statements."""
        if not ids:
            return
        ph = ",".join("?" for _ in ids)
        self.conn.execute(f"DELETE FROM relations WHERE memory_id IN ({ph})", ids)
        self.conn.execute(f"DELETE FROM memories WHERE id IN ({ph})", ids)
        self.conn.commit()

    def all(self) -> list[Memory]:
        rows = self.conn.execute("SELECT * FROM memories ORDER BY id").fetchall()
        return [self._row_to_memory(r) for r in rows]

    def add_many(self, memories: list[Memory]) -> list[int]:
        if not memories:
            return []
        # sqlite3.executemany.lastrowid is unreliable (None) on this build;
        # use explicit transaction + per-row insert returning lastrowid, or
        # query the tail. Simpler and portable: iterate add() inside a transaction.
        ids: list[int] = []
        self.conn.execute("BEGIN")
        try:
            for m in memories:
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
                ids.append(int(cur.lastrowid))
            self.conn.commit()
        except Exception:
            logger.exception("add_many batch failed — rolling back")
            self.conn.rollback()
            raise
        return ids

    def recent(self, limit: int | None = 100, offset: int = 0) -> list[Memory]:
        """Most-recent-first pagination at the SQL level (None = unlimited)."""
        o = max(0, int(offset))
        if limit is None or int(limit) == 0:
            rows = self.conn.execute(
                "SELECT * FROM memories ORDER BY created_at DESC, id DESC LIMIT -1 OFFSET ?",
                (o,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM memories ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (max(0, int(limit)), o),
            ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def top_by_importance(self, top_n: int, min_importance: float = 0.0) -> list[Memory]:
        """Top-N memories by importance (desc), then access count (desc).

        Lightweight scan: only reads the columns persistent-context needs
        (id, content, importance, access_count) — never the embedding blob,
        which is the bulk of every row. Called on every provider turn, so
        avoiding a full SELECT * + numpy decode of the whole store matters.
        """
        rows = self.conn.execute(
            "SELECT id, content, importance, access_count FROM memories "
            "WHERE importance >= ? "
            "ORDER BY importance DESC, access_count DESC, id DESC "
            "LIMIT ?",
            (float(min_importance), int(max(0, top_n) or 0) or 1),
        ).fetchall()
        out: list[Memory] = []
        for r in rows:
            m = Memory(
                id=int(r["id"]),
                content=str(r["content"] or ""),
                importance=float(r["importance"] or 0.0),
                access_count=int(r["access_count"] or 0),
            )
            out.append(m)
        return out

    def temporal_scan(self, limit: int | None = None) -> list[tuple[int, str, int]]:
        """Lightweight rows (id, created_at, access_count) for temporal scoring.

        Avoids parsing JSON metadata/tags and decoding embeddings for every
        memory — temporal recall only needs creation time and access count.
        """
        limit_sql = "" if limit is None else f" LIMIT {int(limit)}"
        rows = self.conn.execute(
            f"SELECT id, created_at, access_count FROM memories{limit_sql}"
        ).fetchall()
        return [(int(r["id"]), str(r["created_at"]), int(r["access_count"] or 0)) for r in rows]

    def scan_embeddings(self) -> tuple[list[int], list[list[float]]]:
        """Lightweight (id, embedding) pairs for vectorized scans.

        Only reads the embedding blob (no JSON/tags/content decode), so the
        rule auto-replace scan can stay vectorized on large stores without
        materializing full Memory objects for every row.
        """
        rows = self.conn.execute(
            "SELECT id, embedding FROM memories WHERE embedding IS NOT NULL"
        ).fetchall()
        ids = [int(r["id"]) for r in rows]
        vecs = [np.frombuffer(r["embedding"], dtype=np.float32).tolist() for r in rows]
        return ids, vecs

    def scan_embeddings_matrix(self) -> tuple[list[int], np.ndarray]:
        """(id list, N×D float32 matrix) for batched cosine scans.

        Faster than :meth:`scan_embeddings` for large stores: stacks the raw
        embedding blobs into one matrix without an intermediate Python list
        of lists, so the rule auto-replace scan stays a single matmul.
        """
        rows = self.conn.execute(
            "SELECT id, embedding FROM memories WHERE embedding IS NOT NULL"
        ).fetchall()
        if not rows:
            return [], np.empty((0, 0), dtype=np.float32)
        ids = [int(r["id"]) for r in rows]
        mat = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
        return ids, mat

    def touch_memories(self, ids: list[int]) -> None:
        """Bump access_count + last_accessed_at for *ids* in one statement.

        Called after a recall to mark which memories were surfaced. Batches
        the per-memory access bookkeeping that would otherwise be one
        ``UPDATE`` per result row (N writes per turn).
        """
        if not ids:
            return
        import time

        now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        ph = ",".join("?" for _ in ids)
        self.conn.execute(
            f"UPDATE memories SET access_count = access_count + 1, "
            f"last_accessed_at = ? "
            f"WHERE id IN ({ph})",
            (now, *ids),
        )
        self.conn.commit()

    def update_importances(self, pairs: list[tuple[float, int]]) -> None:
        """Bulk-update importance for (importance, id) pairs in one pass."""
        if not pairs:
            return
        self.conn.executemany(
            "UPDATE memories SET importance = ? WHERE id = ?",
            [(float(imp), int(_id)) for imp, _id in pairs],
        )
        self.conn.commit()

    def keyword_search(self, query: str, limit: int | None = 10) -> list[tuple[Memory, float]]:
        safe = _sanitize_fts_query(query)
        if limit is None:
            rows = self.conn.execute(
                "SELECT m.*, bm25(memories_fts) AS rank "
                "FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid "
                "WHERE memories_fts MATCH ? ORDER BY rank",
                (safe,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT m.*, bm25(memories_fts) AS rank "
                "FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid "
                "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                (safe, int(limit)),
            ).fetchall()
        return [(self._row_to_memory(r), -float(r["rank"])) for r in rows]

    def vector_search(self, vec: list[float], limit: int | None = 10) -> list[tuple[Memory, float]]:
        q = np.asarray(vec, dtype=np.float32)
        qn = float(np.linalg.norm(q))
        if qn == 0:
            return []

        # Vectorized cosine similarity: load only embeddings into one matrix
        # and compute dot products via matmul (identical results to the
        # per-row loop, but O(N) in numpy instead of Python).
        rows = self.conn.execute(
            "SELECT id, embedding FROM memories WHERE embedding IS NOT NULL"
        ).fetchall()
        if not rows:
            return []

        ids = np.asarray([r["id"] for r in rows], dtype=np.int64)
        mat = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
        norms = np.linalg.norm(mat, axis=1)
        sims = (mat @ q) / (norms * qn + 1e-12)

        # Top-k via argpartition (O(N) instead of full sort).
        if limit is not None and limit < len(sims):
            k = int(limit)
            idx = np.argpartition(-sims, k - 1)[:k]
            idx = idx[np.argsort(-sims[idx])]
        else:
            idx = np.argsort(-sims)

        # Fetch full rows only for the top-k winners.
        top_ids = [int(ids[i]) for i in idx]
        id_ph = ",".join("?" for _ in top_ids)
        full_rows = self.conn.execute(
            f"SELECT * FROM memories WHERE id IN ({id_ph})", top_ids
        ).fetchall()
        full_by_id = {int(r["id"]): r for r in full_rows}
        results: list[tuple[Memory, float]] = []
        for i in idx:
            row = full_by_id.get(int(ids[i]))
            if row is not None:
                results.append((self._row_to_memory(row), float(sims[i])))
        return results

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        return int(row[0])

    def by_tags(self, tags: list[str]) -> set[int]:
        if not tags:
            return set()
        rows = self.conn.execute("SELECT id, tags FROM memories").fetchall()
        import json as _json

        wanted = set(tags)
        ids: set[int] = set()
        for r in rows:
            try:
                tlist = _json.loads(r["tags"] or "[]")
            except Exception:  # noqa: BLE001
                tlist = []
            if wanted & set(tlist):
                ids.add(int(r["id"]))
        return ids

    def close(self) -> None:
        # Close every thread-local connection; a connection created on another
        # thread cannot be closed from here, so each thread's conn is closed
        # by the thread that owns it (or left to GC).
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except sqlite3.ProgrammingError:
                logger.warning("sqlite close skipped: connection owned by another thread")
                return
            self._local.conn = None
