from __future__ import annotations

import heapq
import json
import logging
import math
import sqlite3
import threading
from itertools import islice
import threading

import numpy as np

from luminary_memory.backends.base import MemoryBackend
from luminary_memory.schema import init_schema
from luminary_memory.scope import scope_sql, sqlite_valid_epoch
from luminary_memory.types import Memory

logger = logging.getLogger(__name__)


def _safe_float(value, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _safe_unit_float(value, default: float) -> float:
    return max(0.0, min(1.0, _safe_float(value, default)))


def _safe_int(value, default: int = 0) -> int:
    try:
        parsed = float(value)
        return int(parsed) if math.isfinite(parsed) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _optional_int(value) -> int | None:
    if value is None:
        return None
    try:
        parsed = float(value)
        return max(0, int(parsed)) if math.isfinite(parsed) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _sanitize_fts_query(query: str) -> str:
    """Build a safe FTS5 query from plain user text.

    Without this, characters like ``*``, ``NEAR``, or quoted phrases can
    change the query into something the user did not intend (and can raise
    syntax errors on malformed input). We keep only word characters.

    Terms are joined with ``OR`` so a multi-word query matches memories that
    contain *any* of the terms, and FTS5's ``bm25`` ranking lifts documents
    that match more of them. A default AND join would return zero hits for
    natural multi-term queries — the exact failure that left keyword recall
    empty while the rule was in the store.
    """
    import re

    cleaned = re.sub(r"[^\w\s]", " ", query)
    terms = cleaned.split()
    if not terms:
        return '" "'
    # Escape any stray FTS5 operators inside terms (defensive — \w already
    # excludes them, but keep the query injection-safe).
    safe_terms = []
    for t in terms:
        t = t.strip('"')
        safe_terms.append(f'"{t}"')
    return " OR ".join(safe_terms)


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
            conn.create_function("memory_valid_epoch", 1, sqlite_valid_epoch, deterministic=True)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            # WAL lets the Hermes writer and prefetch reader coexist without
            # serializing the whole store.  In-memory databases and read-only
            # paths may reject the pragma, so keep it best-effort.
            try:
                conn.execute("PRAGMA journal_mode = WAL")
            except sqlite3.DatabaseError:
                pass
            init_schema(conn)
            self._local.conn = conn
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._get_conn()

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        def _json(value, default):
            try:
                return json.loads(value or json.dumps(default))
            except (TypeError, ValueError, json.JSONDecodeError):
                return default

        metadata = _json(row["metadata"], {})
        tags = _json(row["tags"], [])
        if not isinstance(metadata, dict):
            metadata = {}
        if not isinstance(tags, list):
            tags = []
        m = Memory(
            id=row["id"],
            content=row["content"],
            metadata=metadata,
            source=row["source"],
            tags=[str(tag) for tag in tags],
            importance=_safe_unit_float(row["importance"], 0.5),
            ttl_seconds=_optional_int(row["ttl_seconds"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_accessed_at=row["last_accessed_at"],
            access_count=_safe_int(row["access_count"]),
            user_id=row["user_id"],
            session_id=row["session_id"],
            workspace_id=row["workspace_id"],
            agent_id=row["agent_id"],
            observed_at=row["observed_at"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            status=str(row["status"] or "active"),
            confidence=_safe_unit_float(row["confidence"], 1.0),
            evidence_quote=row["evidence_quote"],
            source_id=row["source_id"],
            claim_key=row["claim_key"],
            supersedes_id=row["supersedes_id"],
            content_hash=row["content_hash"],
            needs_reindex=bool(row["needs_reindex"]),
        )
        emb = row["embedding"]
        if emb is not None:
            try:
                vector = np.frombuffer(emb, dtype=np.float32)
                if vector.size and np.isfinite(vector).all():
                    m.embedding = vector.tolist()
            except (TypeError, ValueError):
                # A malformed legacy blob must not make list/get/recall
                # unusable; keyword and graph recall can still operate.
                m.embedding = None
        return m

    @staticmethod
    def _encode_embedding(vec: list[float] | None) -> bytes | None:
        if vec is None:
            return None
        try:
            array = np.asarray(vec, dtype=np.float32)
        except (TypeError, ValueError):
            return None
        if array.ndim != 1 or not array.size or not np.isfinite(array).all():
            return None
        return array.tobytes()

    def _insert_values(self, m: Memory) -> tuple:
        return (
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
            m.user_id,
            m.session_id,
            m.workspace_id,
            m.agent_id,
            m.observed_at,
            m.valid_from,
            m.valid_to,
            m.status or "active",
            float(m.confidence),
            m.evidence_quote,
            m.source_id,
            m.claim_key,
            m.supersedes_id,
            m.content_hash,
            int(bool(m.needs_reindex)),
        )

    def _insert_row(self, m: Memory):
        return self.conn.execute(
            "INSERT INTO memories (content, metadata, source, tags, importance, "
            "ttl_seconds, created_at, updated_at, last_accessed_at, access_count, embedding, "
            "user_id, session_id, workspace_id, agent_id, observed_at, valid_from, valid_to, "
            "status, confidence, evidence_quote, source_id, claim_key, supersedes_id, "
            "content_hash, needs_reindex) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            self._insert_values(m),
        )

    def _find_active_hash_exact(self, m: Memory) -> Memory | None:
        if not m.content_hash:
            return None
        row = self.conn.execute(
            "SELECT * FROM memories WHERE content_hash = ? "
            "AND COALESCE(user_id, '') = COALESCE(?, '') "
            "AND COALESCE(workspace_id, '') = COALESCE(?, '') "
            "AND COALESCE(agent_id, '') = COALESCE(?, '') "
            "AND COALESCE(session_id, '') = COALESCE(?, '') "
            "AND COALESCE(status, 'active') = 'active' ORDER BY id LIMIT 1",
            (
                m.content_hash,
                m.user_id,
                m.workspace_id,
                m.agent_id,
                m.session_id,
            ),
        ).fetchone()
        return self._row_to_memory(row) if row else None

    def add_with_status(self, m: Memory) -> tuple[int, bool]:
        """Atomically insert or resolve an exact active duplicate."""
        try:
            cur = self._insert_row(m)
            self.conn.commit()
            return int(cur.lastrowid), True
        except sqlite3.IntegrityError as exc:
            self.conn.rollback()
            # Only the scoped active-hash index is an expected duplicate race.
            # Other integrity failures (for example a malformed NOT NULL row)
            # must remain visible to callers instead of being misreported as a
            # successful deduplication.
            if "uq_memories_active_scope_hash" not in str(exc):
                raise
            existing = self._find_active_hash_exact(m)
            if existing is None or existing.id is None:
                raise
            return existing.id, False

    def add(self, m: Memory) -> int:
        return self.add_with_status(m)[0]

    def supersede_and_add(self, predecessor: Memory, successor: Memory, retired_at: str) -> int:
        """Commit the exact predecessor transition and new version together."""
        if predecessor.id is None or successor.supersedes_id != predecessor.id:
            raise ValueError("invalid supersession predecessor")
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            cur = self.conn.execute(
                "UPDATE memories SET status = 'superseded', valid_to = COALESCE(valid_to, ?) "
                "WHERE id = ? AND claim_key = ? AND status IN ('active', 'conflicted') "
                "AND COALESCE(user_id, '') = COALESCE(?, '') "
                "AND COALESCE(workspace_id, '') = COALESCE(?, '') "
                "AND COALESCE(agent_id, '') = COALESCE(?, '') "
                "AND COALESCE(session_id, '') = COALESCE(?, '')",
                (retired_at, predecessor.id, successor.claim_key, successor.user_id,
                 successor.workspace_id, successor.agent_id, successor.session_id),
            )
            if cur.rowcount != 1:
                raise ValueError("supersession predecessor is no longer eligible")
            inserted = self._insert_row(successor)
            self.conn.execute(
                "UPDATE claims SET status = 'superseded', valid_to = COALESCE(valid_to, ?) "
                "WHERE memory_id = ? AND status IN ('active', 'conflicted')",
                (retired_at, predecessor.id),
            )
            self.conn.commit()
            return int(inserted.lastrowid)
        except Exception:
            self.conn.rollback()
            raise


    def get(self, id: int) -> Memory | None:
        row = self.conn.execute("SELECT * FROM memories WHERE id = ?", (id,)).fetchone()
        return self._row_to_memory(row) if row else None

    def get_many(self, ids: list[int]) -> dict[int, Memory]:
        """Batch get — one SELECT for many ids instead of N per-id queries."""
        if not ids:
            return {}
        out: dict[int, Memory] = {}
        # Keep a margin below SQLite's common 999-variable limit so callers
        # can safely use this method for long-lived maintenance batches.
        for start in range(0, len(ids), 900):
            chunk = ids[start : start + 900]
            ph = ",".join("?" for _ in chunk)
            rows = self.conn.execute(
                f"SELECT * FROM memories WHERE id IN ({ph})", chunk
            ).fetchall()
            out.update({int(r["id"]): self._row_to_memory(r) for r in rows})
        return out

    def find_by_hash(self, content_hash: str, scope: dict | None = None) -> Memory | None:
        where, params = scope_sql(scope, alias="m", include_global=False)
        row = self.conn.execute(
            f"SELECT m.* FROM memories m WHERE m.content_hash = ? AND {where} "
            "ORDER BY m.id LIMIT 1",
            (content_hash, *params),
        ).fetchone()
        return self._row_to_memory(row) if row else None

    def find_by_claim_key(self, claim_key: str, scope: dict | None = None) -> list[Memory]:
        where, params = scope_sql(
            scope, alias="m", include_global=False, active_only=False
        )
        rows = self.conn.execute(
            f"SELECT m.* FROM memories m WHERE m.claim_key = ? AND {where} ORDER BY m.id",
            (claim_key, *params),
        ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    def record_event(
        self,
        event_type: str,
        memory_id: int | None,
        before: dict | None = None,
        after: dict | None = None,
        actor: str | None = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO memory_events(memory_id, event_type, before_json, after_json, actor) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                memory_id,
                event_type,
                json.dumps(before, ensure_ascii=False) if before is not None else None,
                json.dumps(after, ensure_ascii=False) if after is not None else None,
                actor,
            ),
        )
        self.conn.commit()

    def add_evidence(
        self,
        memory_id: int,
        quote: str,
        source_id: str | None = None,
        observed_at: str | None = None,
        extractor: str | None = None,
        confidence: float = 1.0,
    ) -> None:
        if not quote:
            return
        self.conn.execute(
            "INSERT INTO memory_evidence(memory_id, quote, source_id, observed_at, extractor, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (memory_id, quote, source_id, observed_at, extractor, float(confidence)),
        )
        self.conn.commit()

    def record_episode(self, episode_id: str, content: str, **metadata) -> None:
        """Append the raw source once; an episode is immutable by contract."""
        self.conn.execute(
            "INSERT OR IGNORE INTO episodes "
            "(id, content, source, metadata, user_id, session_id, workspace_id, agent_id, observed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(episode_id),
                str(content),
                metadata.get("source"),
                json.dumps(metadata.get("metadata") or {}, ensure_ascii=False),
                metadata.get("user_id"),
                metadata.get("session_id"),
                metadata.get("workspace_id"),
                metadata.get("agent_id"),
                metadata.get("observed_at"),
            ),
        )
        self.conn.commit()

    def recent_episodes(
        self,
        limit: int = 10,
        scope: dict | None = None,
        include_global: bool = False,
    ) -> list[dict]:
        """Return newest episode rows under the requested scope.

        Unlike memory recall, session continuity must never widen an identity
        boundary. Callers therefore opt into global compatibility explicitly;
        the provider uses exact scope matching for its current session ledger.
        """
        try:
            effective_limit = max(0, int(limit))
        except (TypeError, ValueError):
            effective_limit = 0
        if effective_limit == 0:
            return []

        where, params = scope_sql(
            scope,
            alias="e",
            include_global=bool(include_global),
            active_only=False,
        )
        rows = self.conn.execute(
            "SELECT e.id, e.content, e.source, e.metadata, e.user_id, "
            "e.session_id, e.workspace_id, e.agent_id, e.observed_at, e.created_at "
            f"FROM episodes e WHERE {where} "
            "ORDER BY e.created_at DESC, e.rowid DESC LIMIT ?",
            (*params, effective_limit),
        ).fetchall()

        result: list[dict] = []
        for row in rows:
            try:
                metadata = json.loads(row[3] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            result.append(
                {
                    "id": row[0],
                    "content": row[1],
                    "source": row[2],
                    "metadata": metadata,
                    "user_id": row[4],
                    "session_id": row[5],
                    "workspace_id": row[6],
                    "agent_id": row[7],
                    "observed_at": row[8],
                    "created_at": row[9],
                }
            )
        return result

    def add_claim(self, memory_id: int, claim: dict, **scope) -> None:
        """Write one validated atomic claim and its supporting quote."""
        subject = str(claim.get("subject") or "").strip()
        predicate = str(claim.get("predicate") or "").strip()
        object_value = str(claim.get("object") or "").strip()
        quote = str(claim.get("evidence_quote") or "").strip()
        if not subject or not predicate or not object_value or not quote:
            return
        confidence = _safe_unit_float(claim.get("confidence"), 1.0)
        try:
            cur = self.conn.execute(
                "INSERT INTO claims "
                "(memory_id, subject, predicate, object, polarity, status, confidence, evidence_quote, "
                "source_episode_id, user_id, session_id, workspace_id, agent_id, observed_at, valid_from, valid_to) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    memory_id,
                    subject,
                    predicate,
                    object_value,
                    str(claim.get("polarity") or "positive"),
                    str(claim.get("status") or "active"),
                    confidence,
                    quote,
                    claim.get("source_episode_id"),
                    scope.get("user_id"),
                    scope.get("session_id"),
                    scope.get("workspace_id"),
                    scope.get("agent_id"),
                    claim.get("observed_at"),
                    claim.get("valid_from"),
                    claim.get("valid_to"),
                ),
            )
            claim_id = int(cur.lastrowid)
            self.conn.execute(
                "INSERT INTO claim_evidence "
                "(claim_id, quote, source_episode_id, confidence) VALUES (?, ?, ?, ?)",
                (claim_id, quote, claim.get("source_episode_id"), confidence),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def sync_claim_status(
        self,
        memory_id: int,
        status: str,
        valid_to: str | None = None,
    ) -> None:
        self.conn.execute(
            "UPDATE claims SET status = ?, valid_to = COALESCE(valid_to, ?) "
            "WHERE memory_id = ? AND status IN ('active', 'conflicted')",
            (str(status), valid_to, memory_id),
        )
        self.conn.commit()

    def update(self, m: Memory) -> None:
        if m.id is None:
            raise ValueError("cannot update a memory without an id")
        self.conn.execute(
            "UPDATE memories SET content=?, metadata=?, source=?, tags=?, importance=?, "
            "ttl_seconds=?, updated_at=?, last_accessed_at=?, access_count=?, embedding=?, "
            "user_id=?, session_id=?, workspace_id=?, agent_id=?, observed_at=?, valid_from=?, "
            "valid_to=?, status=?, confidence=?, evidence_quote=?, source_id=?, claim_key=?, "
            "supersedes_id=?, content_hash=?, needs_reindex=? "
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
                m.user_id,
                m.session_id,
                m.workspace_id,
                m.agent_id,
                m.observed_at,
                m.valid_from,
                m.valid_to,
                m.status or "active",
                float(m.confidence),
                m.evidence_quote,
                m.source_id,
                m.claim_key,
                m.supersedes_id,
                m.content_hash,
                int(bool(m.needs_reindex)),
                m.id,
            ),
        )
        self.conn.commit()

    def delete(self, id: int) -> None:
        # Relations reference memories via FK; delete them first (manual cascade).
        self.conn.execute("DELETE FROM relations WHERE memory_id = ?", (id,))
        self.conn.execute("DELETE FROM memories WHERE id = ?", (id,))
        self.conn.commit()

    def rehome_memory_references(self, source_id: int, target_id: int) -> None:
        """Preserve evidence/claims/graph edges when a duplicate is removed."""
        self.conn.execute(
            "UPDATE memory_evidence SET memory_id = ? WHERE memory_id = ?",
            (target_id, source_id),
        )
        self.conn.execute(
            "UPDATE claims SET memory_id = ? WHERE memory_id = ?",
            (target_id, source_id),
        )
        self.conn.execute(
            "UPDATE relations SET memory_id = ? WHERE memory_id = ?",
            (target_id, source_id),
        )
        self.conn.commit()

    def delete_many(self, ids: list[int]) -> None:
        """Batch delete (relations + memories) in two statements."""
        if not ids:
            return
        for start in range(0, len(ids), 450):
            chunk = ids[start : start + 450]
            ph = ",".join("?" for _ in chunk)
            self.conn.execute(f"DELETE FROM relations WHERE memory_id IN ({ph})", chunk)
            self.conn.execute(f"DELETE FROM memories WHERE id IN ({ph})", chunk)
        self.conn.commit()

    def all(self) -> list[Memory]:
        rows = self.conn.execute("SELECT * FROM memories ORDER BY id").fetchall()
        return [self._row_to_memory(r) for r in rows]

    def add_many_with_status(self, memories: list[Memory]) -> list[tuple[int, bool]]:
        if not memories:
            return []
        results: list[tuple[int, bool]] = []
        self.conn.execute("BEGIN")
        try:
            for m in memories:
                try:
                    cur = self._insert_row(m)
                except sqlite3.IntegrityError as exc:
                    if "uq_memories_active_scope_hash" not in str(exc):
                        raise
                    existing = self._find_active_hash_exact(m)
                    if existing is None or existing.id is None:
                        raise
                    results.append((existing.id, False))
                else:
                    results.append((int(cur.lastrowid), True))
            self.conn.commit()
        except Exception:
            logger.exception("add_many batch failed — rolling back")
            self.conn.rollback()
            raise
        return results

    def add_many(self, memories: list[Memory]) -> list[int]:
        return [memory_id for memory_id, _inserted in self.add_many_with_status(memories)]

    def recent(
        self,
        limit: int | None = 100,
        offset: int = 0,
        scope: dict | None = None,
        include_global: bool = True,
    ) -> list[Memory]:
        """Most-recent-first pagination at the SQL level (None = unlimited)."""
        o = max(0, int(offset))
        where, params = scope_sql(scope, alias="m", include_global=include_global)
        if limit is None or int(limit) == 0:
            rows = self.conn.execute(
                f"SELECT m.* FROM memories m WHERE {where} "
                "ORDER BY created_at DESC, id DESC LIMIT -1 OFFSET ?",
                (*params, o),
            ).fetchall()
        else:
            rows = self.conn.execute(
                f"SELECT m.* FROM memories m WHERE {where} "
                "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (*params, max(0, int(limit)), o),
            ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def top_by_importance(
        self,
        valid_only: bool = False,
        min_importance: float = 0.0,
        scope: dict | None = None,
        include_global: bool = True,
        valid_only: bool = False,
    ) -> list[Memory]:
        """Top-N memories by importance (desc), then access count (desc).

        Lightweight scan: only reads the columns recall/core scans need
        (id, content, importance, access_count) — never the embedding blob,
        which is the bulk of every row. Called on every provider turn, so
        avoiding a full SELECT * + numpy decode of the whole store matters.
        """
        if int(top_n) <= 0:
            return []
        where, scope_params = scope_sql(
            scope, alias="m", include_global=include_global, valid_only=valid_only
        )
        where, scope_params = scope_sql(
            scope, alias="m", include_global=include_global, valid_only=valid_only
        )
            f"SELECT m.id, m.content, m.importance, m.access_count FROM memories m "
            f"WHERE {where} AND m.importance >= ? "
            "ORDER BY importance DESC, access_count DESC, id DESC "
            "LIMIT ?",
            (*scope_params, float(min_importance), int(max(0, top_n) or 0) or 1),
        ).fetchall()
        ids = [int(r["id"]) for r in rows]
        full = self.get_many(ids)
        return [full[mid] for mid in ids if mid in full]

    def by_tag_top(
        self,
        tag: str,
        top_n: int,
        scope: dict | None = None,
        include_global: bool = True,
    ) -> list[Memory]:
        """Return a stable insertion-ordered slice of memories carrying *tag*.

        Lean scan (no embedding blobs) for the DB-backed core-memory block
        that is auto-loaded into the system prompt every session — the
        luminary equivalent of a native ``MEMORY.md``. Core membership is a
        lifecycle decision, not a relevance score: changing importance or
        access frequency must not silently replace one always-loaded rule with
        another. ``id`` is the durable insertion order and the deterministic
        tie-breaker.
        """
        if int(top_n) <= 0:
            return []
        where, scope_params = scope_sql(scope, alias="m", include_global=include_global)
        rows = self.conn.execute(
            f"SELECT m.id, m.content, m.importance, m.access_count FROM memories m "
            f"WHERE {where} AND EXISTS ("
            "SELECT 1 FROM json_each(m.tags) AS tag WHERE tag.value = ?) "
            "ORDER BY id ASC "
            "LIMIT ?",
            (*scope_params, tag, int(max(0, top_n) or 0) or 1),
        ).fetchall()
        ids = [int(r["id"]) for r in rows]
        full = self.get_many(ids)
    def iter_temporal_scan(
        self,
        scope: dict | None = None,
        include_global: bool = True,
        include_observed: bool = False,
    ):
        """Yield scoped, valid lightweight rows without materializing the store."""
        where, params = scope_sql(scope, alias="m", include_global=include_global, valid_only=True)
        date_column = "COALESCE(m.observed_at, m.created_at)" if include_observed else "m.created_at"
        cursor = self.conn.execute(
            f"WHERE {where}",
            f"WHERE {where} ORDER BY m.id",
            params,
        )
        for row in cursor:
            yield int(row["id"]), str(row["temporal_at"]), _safe_int(row["access_count"])

    def temporal_scan(
        self,
        limit: int | None = None,
        scope: dict | None = None,
        include_global: bool = True,
        include_observed: bool = False,
    ) -> list[tuple[int, str, int]]:
        """Return lightweight temporal rows for callers needing a list."""
        rows = self.iter_temporal_scan(
            scope=scope, include_global=include_global, include_observed=include_observed,
        )
        return list(rows) if limit is None or int(limit) < 0 else list(islice(rows, int(limit)))
        mat = np.vstack([vec for _mid, vec in parsed])
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
        for start in range(0, len(ids), 900):
            chunk = ids[start : start + 900]
            ph = ",".join("?" for _ in chunk)
            self.conn.execute(
                f"UPDATE memories SET access_count = access_count + 1, "
                f"last_accessed_at = ? "
                f"WHERE id IN ({ph})",
                (now, *chunk),
            )
        self.conn.commit()

    def update_importances(self, pairs: list[tuple[float, int]]) -> None:
        """Bulk-update importance for (importance, id) pairs in one pass."""
        if not pairs:
            return
        normalized = [(float(imp), int(_id)) for imp, _id in pairs]
        for start in range(0, len(normalized), 450):
            self.conn.executemany(
                "UPDATE memories SET importance = ? WHERE id = ?",
                normalized[start : start + 450],
            )
        self.conn.commit()

    def keyword_search(
        self,
        query: str,
        limit: int | None = 10,
        scope: dict | None = None,
        include_global: bool = True,
    ) -> list[tuple[Memory, float]]:
        if limit is not None and int(limit) == 0:
            return []
        safe = _sanitize_fts_query(query)
        where, params = scope_sql(scope, alias="m", include_global=include_global, valid_only=True)
        if limit is None:
            rows = self.conn.execute(
                "SELECT m.*, bm25(memories_fts) AS rank "
                "FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid "
                f"WHERE memories_fts MATCH ? AND {where} ORDER BY rank",
                (safe, *params),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT m.*, bm25(memories_fts) AS rank "
                "FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid "
                f"WHERE memories_fts MATCH ? AND {where} ORDER BY rank LIMIT ?",
                (safe, *params, int(limit)),
            ).fetchall()
        results: dict[int, tuple[Memory, float]] = {
            int(r["id"]): (self._row_to_memory(r), -float(r["rank"])) for r in rows
        }

        # FTS5 tokenization intentionally treats punctuation as a separator,
        # which makes identifiers such as ``GPT-4o``, ``C++``, ticket IDs and
        # URLs lossy.  Add a parameterized exact-substring arm for those
        # tokens; it is still scope/status-filtered before candidates enter
        # fusion and therefore cannot become a leakage fallback.
        import re

        raw_terms = [term.strip(".,") for term in re.findall(r"[^\s,;!?()\"'<>]+", query or "")]
        stop_terms = {
            "a", "an", "and", "are", "as", "at", "be", "does", "for", "from",
            "how", "is", "it", "of", "on", "or", "the", "to", "use", "was",
            "what", "when", "where", "which", "who", "will", "with", "you",
        }
        identifier_terms = [
            term for term in raw_terms
            if term.casefold() not in stop_terms
            and any(char in term for char in "+-/:.@=#")
        ]
        if identifier_terms:
            clauses = " OR ".join("LOWER(m.content) LIKE LOWER(?)" for _ in identifier_terms)
            exact_rows = self.conn.execute(
                f"SELECT m.* FROM memories m WHERE ({clauses}) AND {where}",
                tuple(f"%{term}%" for term in identifier_terms) + tuple(params),
            ).fetchall()
            for row in exact_rows:
                memory = self._row_to_memory(row)
                content = memory.content.casefold()
                exact_score = 2.0 + sum(term.casefold() in content for term in identifier_terms)
                previous = results.get(int(row["id"]))
                if previous is None or exact_score > previous[1]:
                    results[int(row["id"])] = (memory, exact_score)

        ordered = sorted(results.values(), key=lambda item: item[1], reverse=True)
    def vector_search(
        self,
        vec: list[float],
        limit: int | None = 10,
        scope: dict | None = None,
        include_global: bool = True,
    ) -> list[tuple[Memory, float]]:
        if limit is not None and int(limit) == 0:
            return []
        q = np.asarray(vec, dtype=np.float32)
        if q.ndim != 1 or not q.size or not np.isfinite(q).all():
            return []
        qn = float(np.linalg.norm(q))
        if not math.isfinite(qn) or qn == 0:
            return []

        # Keep the scan's transient matrix bounded independently of corpus size.
        # The heap retains only the best K scores; unlimited output necessarily
        # retains all winning (id, score) pairs, but never all embedding blobs.
        k = int(limit) if limit is not None else None
        bounded = k is not None and k > 0
        best: list[tuple[float, int]] = []
        where, params = scope_sql(scope, alias="m", include_global=include_global, valid_only=True)
        cursor = self.conn.execute(
            f"WHERE m.embedding IS NOT NULL AND {where}",
            f"WHERE m.embedding IS NOT NULL AND {where} ORDER BY m.id",
            params,
        )
        batch: list[tuple[int, np.ndarray]] = []

        def rank_batch() -> None:
            if not batch:
                return
            matrix = np.stack([embedding for _, embedding in batch])
            norms = np.linalg.norm(matrix, axis=1)
            sims = (matrix @ q) / (norms * qn + 1e-12)
            for (mid, _), sim in zip(batch, sims):
                score = float(sim)
                if not math.isfinite(score):
                    continue
                candidate = (score, -mid)
                if bounded:
                    if len(best) < k:
                        heapq.heappush(best, candidate)
                    elif candidate > best[0]:
                        heapq.heapreplace(best, candidate)
                else:
                    best.append(candidate)
            batch.clear()

        for row in cursor:
            try:
                embedding = np.frombuffer(row["embedding"], dtype=np.float32)
            except (TypeError, ValueError):
                continue
            if embedding.size != q.size or not np.isfinite(embedding).all():
                continue
            batch.append((int(row["id"]), embedding))
            if len(batch) == 256:
                rank_batch()
        rank_batch()
        if not best:
            return []

        ordered = sorted(best, reverse=True)
        results: list[tuple[Memory, float]] = []
        for start in range(0, len(ordered), 900):
            winners = ordered[start : start + 900]
            ids = [-mid for _, mid in winners]
            placeholders = ",".join("?" for _ in ids)
            rows = self.conn.execute(
                f"SELECT * FROM memories WHERE id IN ({placeholders})", ids,
            ).fetchall()
            by_id = {int(row["id"]): row for row in rows}
            for score, negative_id in winners:
                row = by_id.get(-negative_id)
                if row is not None:
                    results.append((self._row_to_memory(row), score))
        return results
                results.append((self._row_to_memory(row), float(sims[i])))
        return results

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        return int(row[0])

    def by_tags(
        self,
        tags: list[str],
        match: str = "any",
        scope: dict | None = None,
        include_global: bool = True,
    ) -> set[int]:
        if not tags:
            return set()
        where, params = scope_sql(scope, alias="m", include_global=include_global)
        rows = self.conn.execute(
            f"SELECT m.id, m.tags FROM memories m WHERE {where}", params
        ).fetchall()
        wanted = {str(tag) for tag in tags}
        ids: set[int] = set()
        for r in rows:
            try:
                tlist = json.loads(r["tags"] or "[]")
            except Exception:  # noqa: BLE001
                tlist = []
            have = set(tlist)
            matches = wanted <= have if match == "all" else bool(wanted & have)
            if matches:
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
