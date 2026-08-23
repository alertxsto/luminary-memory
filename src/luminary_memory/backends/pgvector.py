from __future__ import annotations

import hashlib
import json
import logging
import math
from typing import Any

from luminary_memory.backends.base import MemoryBackend
from luminary_memory.scope import normalize_scope, scope_sql
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
        return int(float(value))
    except (TypeError, ValueError):
        return default


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
                embedding       vector({self.embedding_dim}),
                user_id         TEXT,
                session_id      TEXT,
                workspace_id    TEXT,
                agent_id        TEXT,
                observed_at     TIMESTAMPTZ,
                valid_from      TIMESTAMPTZ,
                valid_to        TIMESTAMPTZ,
                status          TEXT NOT NULL DEFAULT 'active',
                confidence      DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                evidence_quote  TEXT,
                source_id       TEXT,
                claim_key       TEXT,
                supersedes_id   INTEGER,
                content_hash    TEXT,
                needs_reindex   BOOLEAN NOT NULL DEFAULT FALSE
            )
            """
        )
        # Older deployments may have the original compact memories table.
        # Evolve its base columns before adding the accuracy/lifecycle fields.
        for column, definition in (
            ("metadata", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
            ("source", "TEXT"),
            ("tags", "JSONB NOT NULL DEFAULT '[]'::jsonb"),
            ("importance", "DOUBLE PRECISION NOT NULL DEFAULT 0.5"),
            ("ttl_seconds", "INTEGER"),
            ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT now()"),
            ("updated_at", "TIMESTAMPTZ NOT NULL DEFAULT now()"),
            ("last_accessed_at", "TIMESTAMPTZ"),
            ("access_count", "INTEGER NOT NULL DEFAULT 0"),
            ("embedding", f"vector({self.embedding_dim})"),
        ):
            cur.execute(f"ALTER TABLE memories ADD COLUMN IF NOT EXISTS {column} {definition}")
        for column, definition in (
            ("user_id", "TEXT"),
            ("session_id", "TEXT"),
            ("workspace_id", "TEXT"),
            ("agent_id", "TEXT"),
            ("observed_at", "TIMESTAMPTZ"),
            ("valid_from", "TIMESTAMPTZ"),
            ("valid_to", "TIMESTAMPTZ"),
            ("status", "TEXT NOT NULL DEFAULT 'active'"),
            ("confidence", "DOUBLE PRECISION NOT NULL DEFAULT 1.0"),
            ("evidence_quote", "TEXT"),
            ("source_id", "TEXT"),
            ("claim_key", "TEXT"),
            ("supersedes_id", "INTEGER"),
            ("content_hash", "TEXT"),
            ("needs_reindex", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ):
            cur.execute(f"ALTER TABLE memories ADD COLUMN IF NOT EXISTS {column} {definition}")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(user_id, workspace_id, agent_id, session_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_memories_claim ON memories(user_id, workspace_id, claim_key, status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_memories_hash ON memories(user_id, workspace_id, content_hash)")
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_evidence (
                id BIGSERIAL PRIMARY KEY,
                memory_id INTEGER REFERENCES memories(id) ON DELETE SET NULL,
                quote TEXT NOT NULL,
                source_id TEXT,
                observed_at TIMESTAMPTZ,
                extractor TEXT,
                confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_events (
                id BIGSERIAL PRIMARY KEY,
                memory_id INTEGER,
                event_type TEXT NOT NULL,
                before_json JSONB,
                after_json JSONB,
                actor TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                source TEXT,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                user_id TEXT,
                session_id TEXT,
                workspace_id TEXT,
                agent_id TEXT,
                observed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodes_scope "
            "ON episodes(user_id, workspace_id, agent_id, session_id)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS claims (
                id BIGSERIAL PRIMARY KEY,
                memory_id INTEGER REFERENCES memories(id) ON DELETE SET NULL,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                polarity TEXT NOT NULL DEFAULT 'positive',
                status TEXT NOT NULL DEFAULT 'active',
                confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                evidence_quote TEXT,
                source_episode_id TEXT,
                user_id TEXT,
                session_id TEXT,
                workspace_id TEXT,
                agent_id TEXT,
                observed_at TIMESTAMPTZ,
                valid_from TIMESTAMPTZ,
                valid_to TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_claims_key "
            "ON claims(user_id, workspace_id, subject, predicate, status)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS claim_evidence (
                id BIGSERIAL PRIMARY KEY,
                claim_id BIGINT REFERENCES claims(id) ON DELETE SET NULL,
                quote TEXT NOT NULL,
                source_episode_id TEXT,
                source_offset_start INTEGER,
                source_offset_end INTEGER,
                confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        # Repair legacy rows before installing the database-level exact
        # dedup invariant. The oldest active row remains canonical; derived
        # references move to it and append-only audit/source history stays.
        cur.execute("SELECT id, content FROM memories WHERE content_hash IS NULL")
        for row in cur.fetchall():
            memory_id, content = row[0], row[1]
            normalized = " ".join(str(content or "").strip().split()).casefold()
            content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            cur.execute(
                "UPDATE memories SET content_hash = %s WHERE id = %s AND content_hash IS NULL",
                (content_hash, memory_id),
            )
        cur.execute(
            "SELECT COALESCE(user_id, ''), COALESCE(workspace_id, ''), "
            "COALESCE(agent_id, ''), COALESCE(session_id, ''), content_hash, MIN(id) "
            "FROM memories WHERE COALESCE(status, 'active') = 'active' "
            "AND content_hash IS NOT NULL "
            "GROUP BY COALESCE(user_id, ''), COALESCE(workspace_id, ''), "
            "COALESCE(agent_id, ''), COALESCE(session_id, ''), content_hash "
            "HAVING COUNT(*) > 1"
        )
        for group in cur.fetchall():
            # Some lightweight test doubles return the previous fixture row
            # for every fetchall call; a real aggregate row has six fields.
            if len(group) != 6:
                continue
            user_id, workspace_id, agent_id, session_id, content_hash, survivor = group
            cur.execute(
                "SELECT id FROM memories WHERE COALESCE(status, 'active') = 'active' "
                "AND content_hash = %s AND COALESCE(user_id, '') = %s "
                "AND COALESCE(workspace_id, '') = %s AND COALESCE(agent_id, '') = %s "
                "AND COALESCE(session_id, '') = %s AND id <> %s",
                (content_hash, user_id, workspace_id, agent_id, session_id, survivor),
            )
            for (duplicate_id,) in cur.fetchall():
                for table in ("memory_evidence", "claims", "relations"):
                    cur.execute(
                        f"UPDATE {table} SET memory_id = %s WHERE memory_id = %s",
                        (survivor, duplicate_id),
                    )
                cur.execute(
                    "UPDATE memories SET supersedes_id = %s WHERE supersedes_id = %s",
                    (survivor, duplicate_id),
                )
                cur.execute("DELETE FROM memories WHERE id = %s", (duplicate_id,))
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_memories_active_scope_hash "
            "ON memories (COALESCE(user_id, ''), COALESCE(workspace_id, ''), "
            "COALESCE(agent_id, ''), COALESCE(session_id, ''), content_hash) "
            "WHERE COALESCE(status, 'active') = 'active' AND content_hash IS NOT NULL"
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
                "access_count", "embedding", "user_id", "session_id", "workspace_id",
                "agent_id", "observed_at", "valid_from", "valid_to", "status", "confidence",
                "evidence_quote", "source_id", "claim_key", "supersedes_id", "content_hash",
                "needs_reindex",
            ]
            d = dict(zip(cols, row))
            emb = d.get("embedding")
        if isinstance(emb, str):
            try:
                emb = json.loads(emb)
            except json.JSONDecodeError:
                emb = None
        if isinstance(emb, (list, tuple)):
            try:
                emb = [float(value) for value in emb]
            except (TypeError, ValueError):
                emb = None
            if emb is not None and (
                not emb or not all(math.isfinite(value) for value in emb)
            ):
                emb = None
        else:
            emb = None
        metadata = _json_load(d.get("metadata"), {})
        tags = _json_load(d.get("tags"), [])
        if not isinstance(metadata, dict):
            metadata = {}
        if not isinstance(tags, list):
            tags = []
        return Memory(
            id=int(d["id"]) if d.get("id") is not None else None,
            content=str(d.get("content") or ""),
            metadata=metadata,
            source=d.get("source"),
            tags=[str(tag) for tag in tags],
            importance=_safe_unit_float(d.get("importance"), 0.5),
            ttl_seconds=d.get("ttl_seconds"),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            last_accessed_at=str(d["last_accessed_at"]) if d.get("last_accessed_at") else None,
            access_count=_safe_int(d.get("access_count")),
            embedding=emb,
            snippet=None,
            user_id=d.get("user_id"),
            session_id=d.get("session_id"),
            workspace_id=d.get("workspace_id"),
            agent_id=d.get("agent_id"),
            observed_at=str(d["observed_at"]) if d.get("observed_at") else None,
            valid_from=str(d["valid_from"]) if d.get("valid_from") else None,
            valid_to=str(d["valid_to"]) if d.get("valid_to") else None,
            status=str(d.get("status") or "active"),
            confidence=_safe_unit_float(d.get("confidence"), 1.0),
            evidence_quote=d.get("evidence_quote"),
            source_id=d.get("source_id"),
            claim_key=d.get("claim_key"),
            supersedes_id=d.get("supersedes_id"),
            content_hash=d.get("content_hash"),
            needs_reindex=bool(d.get("needs_reindex") or False),
        )

    @staticmethod
    def _insert_values(m: Memory) -> tuple:
        return (
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
            bool(m.needs_reindex),
        )

    def _find_active_hash_exact(self, m: Memory) -> Memory | None:
        if not m.content_hash:
            return None
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM memories WHERE content_hash = %s "
            "AND COALESCE(user_id, '') = COALESCE(%s, '') "
            "AND COALESCE(workspace_id, '') = COALESCE(%s, '') "
            "AND COALESCE(agent_id, '') = COALESCE(%s, '') "
            "AND COALESCE(session_id, '') = COALESCE(%s, '') "
            "AND COALESCE(status, 'active') = 'active' ORDER BY id LIMIT 1",
            (m.content_hash, m.user_id, m.workspace_id, m.agent_id, m.session_id),
        )
        row = cur.fetchone()
        return self._row_to_memory(row) if row else None

    def add_with_status(self, m: Memory) -> tuple[int, bool]:
        cur = self.conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO memories (content, metadata, source, tags, importance,
                                      ttl_seconds, created_at, updated_at,
                                      last_accessed_at, access_count, embedding,
                                      user_id, session_id, workspace_id, agent_id,
                                      observed_at, valid_from, valid_to, status, confidence,
                                      evidence_quote, source_id, claim_key, supersedes_id,
                                      content_hash, needs_reindex)
                VALUES (%s, %s::jsonb, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                self._insert_values(m),
            )
            row = cur.fetchone()
            self.conn.commit()
            return int(row[0]) if row else 0, True
        except Exception as exc:
            # Only a unique-index race is recoverable. Do not turn a malformed
            # row, dimension mismatch, or connection/database error into a
            # false duplicate merely because an older row happens to share
            # its content hash.
            self.conn.rollback()
            if not isinstance(exc, self._psycopg.errors.UniqueViolation):
                raise
            try:
                existing = self._find_active_hash_exact(m)
            finally:
                # The lookup itself starts a read transaction in psycopg;
                # close it before returning so a long-lived writer does not
                # retain a snapshot or hold schema locks.
                self.conn.rollback()
            if existing is None or existing.id is None:
                raise
            return existing.id, False

    def add(self, m: Memory) -> int:
        return self.add_with_status(m)[0]

    def get(self, id: int) -> Memory | None:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM memories WHERE id = %s", (id,))
        row = cur.fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            return self._row_to_memory(row)
        return self._row_to_memory(row)

    def find_by_hash(self, content_hash: str, scope: dict | None = None) -> Memory | None:
        where, params = scope_sql(scope, alias="m", include_global=False)
        cur = self.conn.cursor()
        cur.execute(
            f"SELECT m.* FROM memories m WHERE m.content_hash = %s AND "
            f"{where.replace('?', '%s')} ORDER BY m.id LIMIT 1",
            (content_hash, *params),
        )
        row = cur.fetchone()
        return self._row_to_memory(row) if row else None

    def find_by_claim_key(self, claim_key: str, scope: dict | None = None) -> list[Memory]:
        where, params = scope_sql(
            scope, alias="m", include_global=False, active_only=False
        )
        cur = self.conn.cursor()
        cur.execute(
            f"SELECT m.* FROM memories m WHERE m.claim_key = %s AND "
            f"{where.replace('?', '%s')} ORDER BY m.id",
            (claim_key, *params),
        )
        return [self._row_to_memory(row) for row in cur.fetchall()]

    def record_event(
        self,
        event_type: str,
        memory_id: int | None,
        before: dict | None = None,
        after: dict | None = None,
        actor: str | None = None,
    ) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO memory_events(memory_id, event_type, before_json, after_json, actor) "
            "VALUES (%s, %s, %s::jsonb, %s::jsonb, %s)",
            (
                memory_id,
                event_type,
                json.dumps(before) if before is not None else None,
                json.dumps(after) if after is not None else None,
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
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO memory_evidence(memory_id, quote, source_id, observed_at, extractor, confidence) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (memory_id, quote, source_id, observed_at, extractor, float(confidence)),
        )
        self.conn.commit()

    def record_episode(self, episode_id: str, content: str, **metadata) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO episodes "
            "(id, content, source, metadata, user_id, session_id, workspace_id, agent_id, observed_at) "
            "VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO NOTHING",
            (
                str(episode_id),
                str(content),
                metadata.get("source"),
                json.dumps(metadata.get("metadata") or {}),
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
        """Return newest episode rows under an explicit scope."""
        try:
            effective_limit = max(0, int(limit))
        except (TypeError, ValueError):
            effective_limit = 0
        if effective_limit == 0:
            return []

        normalized = normalize_scope(scope)
        clauses: list[str] = []
        params: list[str] = []
        for field in ("user_id", "workspace_id", "agent_id", "session_id"):
            value = normalized.get(field)
            if include_global:
                if value is None:
                    clauses.append(f"(e.{field} IS NULL OR e.{field} = '')")
                else:
                    clauses.append(f"(e.{field} = %s OR e.{field} IS NULL OR e.{field} = '')")
                    params.append(value)
            elif value is not None:
                clauses.append(f"e.{field} = %s")
                params.append(value)
        where = " AND ".join(clauses) or "TRUE"

        cur = self.conn.cursor()
        cur.execute(
            "SELECT e.id, e.content, e.source, e.metadata, e.user_id, "
            "e.session_id, e.workspace_id, e.agent_id, e.observed_at, e.created_at "
            f"FROM episodes e WHERE {where} "
            "ORDER BY e.created_at DESC, e.id DESC LIMIT %s",
            (*params, effective_limit),
        )
        rows = cur.fetchall()
        result: list[dict] = []
        for row in rows:
            metadata = row[3]
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
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
        subject = str(claim.get("subject") or "").strip()
        predicate = str(claim.get("predicate") or "").strip()
        object_value = str(claim.get("object") or "").strip()
        quote = str(claim.get("evidence_quote") or "").strip()
        if not subject or not predicate or not object_value or not quote:
            return
        confidence = _safe_unit_float(claim.get("confidence"), 1.0)
        try:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO claims "
                "(memory_id, subject, predicate, object, polarity, status, confidence, evidence_quote, "
                "source_episode_id, user_id, session_id, workspace_id, agent_id, observed_at, valid_from, valid_to) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "RETURNING id",
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
            row = cur.fetchone()
            claim_id = row[0] if row else None
            if claim_id is not None:
                cur.execute(
                    "INSERT INTO claim_evidence(claim_id, quote, source_episode_id, confidence) "
                    "VALUES (%s, %s, %s, %s)",
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
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE claims SET status = %s, valid_to = COALESCE(valid_to, %s) "
            "WHERE memory_id = %s AND status IN ('active', 'conflicted')",
            (str(status), valid_to, memory_id),
        )
        self.conn.commit()

    def update(self, m: Memory) -> None:
        if m.id is None:
            raise ValueError("cannot update a memory without an id")
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE memories SET content=%s, metadata=%s::jsonb, source=%s, tags=%s::jsonb,
                                importance=%s, ttl_seconds=%s, updated_at=%s,
                                last_accessed_at=%s, access_count=%s, embedding=%s,
                                user_id=%s, session_id=%s, workspace_id=%s, agent_id=%s,
                                observed_at=%s, valid_from=%s, valid_to=%s, status=%s,
                                confidence=%s, evidence_quote=%s, source_id=%s, claim_key=%s,
                                supersedes_id=%s, content_hash=%s, needs_reindex=%s
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
                bool(m.needs_reindex),
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

    def rehome_memory_references(self, source_id: int, target_id: int) -> None:
        """Preserve evidence/claims/graph edges when a duplicate is removed."""
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE memory_evidence SET memory_id = %s WHERE memory_id = %s",
            (target_id, source_id),
        )
        cur.execute(
            "UPDATE claims SET memory_id = %s WHERE memory_id = %s",
            (target_id, source_id),
        )
        cur.execute(
            "UPDATE relations SET memory_id = %s WHERE memory_id = %s",
            (target_id, source_id),
        )
        self.conn.commit()

    def all(self) -> list[Memory]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM memories ORDER BY id")
        rows = cur.fetchall()
        return [self._row_to_memory(r) for r in rows]

    def add_many_with_status(self, memories: list[Memory]) -> list[tuple[int, bool]]:
        if not memories:
            return []
        cur = self.conn.cursor()
        results: list[tuple[int, bool]] = []
        try:
            for m in memories:
                cur.execute(
                    """
                    INSERT INTO memories (content, metadata, source, tags, importance,
                                          ttl_seconds, created_at, updated_at,
                                          last_accessed_at, access_count, embedding,
                                          user_id, session_id, workspace_id, agent_id,
                                          observed_at, valid_from, valid_to, status, confidence,
                                          evidence_quote, source_id, claim_key, supersedes_id,
                                          content_hash, needs_reindex)
                    VALUES (%s, %s::jsonb, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """,
                    self._insert_values(m),
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    results.append((int(row[0]), True))
                    continue
                existing = self._find_active_hash_exact(m)
                if existing is None or existing.id is None:
                    raise RuntimeError(
                        "batch insert was ignored without a resolvable active duplicate"
                    )
                results.append((existing.id, False))
            self.conn.commit()
            return results
        except Exception:
            self.conn.rollback()
            raise

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
        cur = self.conn.cursor()
        o = max(0, int(offset))
        where, params = scope_sql(scope, alias="m", include_global=include_global)
        where = where.replace("?", "%s")
        if limit is None or int(limit) == 0:
            cur.execute(
                f"SELECT m.* FROM memories m WHERE {where} "
                "ORDER BY created_at DESC, id DESC OFFSET %s",
                (*params, o),
            )
        else:
            cur.execute(
                f"SELECT m.* FROM memories m WHERE {where} "
                "ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
                (*params, max(0, int(limit)), o),
            )
        rows = cur.fetchall()
        return [self._row_to_memory(r) for r in rows]

    def top_by_importance(
        self,
        top_n: int,
        min_importance: float = 0.0,
        scope: dict | None = None,
        include_global: bool = True,
    ) -> list[Memory]:
        """Return complete memories for strict recall fallback/core loading."""
        cur = self.conn.cursor()
        where, params = scope_sql(scope, alias="m", include_global=include_global)
        where = where.replace("?", "%s")
        cur.execute(
            f"SELECT m.* FROM memories m WHERE {where} AND m.importance >= %s "
            "ORDER BY m.importance DESC, m.access_count DESC, m.id DESC LIMIT %s",
            (*params, float(min_importance), max(0, int(top_n))),
        )
        return [self._row_to_memory(row) for row in cur.fetchall()]

    def by_tag_top(
        self,
        tag: str,
        top_n: int,
        scope: dict | None = None,
        include_global: bool = True,
    ) -> list[Memory]:
        """Return a stable insertion-ordered slice carrying *tag*.

        Core membership is a lifecycle decision, not a relevance score. Keep
        the PostgreSQL backend aligned with SQLite so access/importance
        updates cannot silently reorder or evict an always-loaded rule.
        """
        cur = self.conn.cursor()
        where, params = scope_sql(scope, alias="m", include_global=include_global)
        where = where.replace("?", "%s")
        cur.execute(
            f"SELECT m.* FROM memories m WHERE {where} AND m.tags @> %s::jsonb "
            "ORDER BY m.id ASC LIMIT %s",
            (*params, json.dumps([tag]), max(0, int(top_n))),
        )
        return [self._row_to_memory(row) for row in cur.fetchall()]

    def keyword_search(
        self,
        query: str,
        limit: int | None = 10,
        scope: dict | None = None,
        include_global: bool = True,
    ) -> list[tuple[Memory, float]]:
        import re

        terms = [term for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9_./:+#@=-]*", query or "") if term]
        if not terms or (limit is not None and int(limit) == 0):
            return []
        cur = self.conn.cursor()
        where, scope_params = scope_sql(scope, alias="m", include_global=include_global)
        where = where.replace("?", "%s")
        patterns = [f"%{term}%" for term in terms]
        match_clause = " OR ".join("m.content ILIKE %s" for _ in terms)
        score_expr = " + ".join(
            "CASE WHEN m.content ILIKE %s THEN 1 ELSE 0 END" for _ in terms
        )
        if limit is None:
            cur.execute(
                f"SELECT m.*, ({score_expr}) AS rank FROM memories m "
                f"WHERE ({match_clause}) AND {where} ORDER BY rank DESC, m.id DESC",
                (*patterns, *patterns, *scope_params),
            )
        else:
            cur.execute(
                f"SELECT m.*, ({score_expr}) AS rank FROM memories m "
                f"WHERE ({match_clause}) AND {where} ORDER BY rank DESC, m.id DESC LIMIT %s",
                (*patterns, *patterns, *scope_params, int(limit)),
            )
        rows = cur.fetchall()
        results: list[tuple[Memory, float]] = []
        for row in rows:
            if isinstance(row, dict):
                rank = float(row.get("rank") or 0.0)
            else:
                rank = float(row[-1] or 0.0) if row else 0.0
            results.append((self._row_to_memory(row), rank / max(1, len(terms))))
        return results

    def vector_search(
        self,
        vec: list[float],
        limit: int | None = 10,
        scope: dict | None = None,
        include_global: bool = True,
    ) -> list[tuple[Memory, float]]:
        if limit is not None and int(limit) == 0:
            return []
        cur = self.conn.cursor()
        where, scope_params = scope_sql(scope, alias="m", include_global=include_global)
        where = where.replace("?", "%s")
        if limit is None:
            cur.execute(
                "SELECT m.*, m.embedding <=> %s::vector AS distance FROM memories m "
                f"WHERE m.embedding IS NOT NULL AND {where} ORDER BY distance",
                (vec, *scope_params),
            )
        else:
            cur.execute(
                "SELECT m.*, m.embedding <=> %s::vector AS distance FROM memories m "
                f"WHERE m.embedding IS NOT NULL AND {where} ORDER BY distance LIMIT %s",
                (vec, *scope_params, int(limit)),
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

    def by_tags(
        self,
        tags: list[str],
        match: str = "any",
        scope: dict | None = None,
        include_global: bool = True,
    ) -> set[int]:
        if not tags:
            return set()
        cur = self.conn.cursor()
        # JSONB tags @> check per tag; fallback to python filter when driver absent.
        try:
            import json as _json

            wanted = set(tags)
            if scope:
                where, scope_params = scope_sql(scope, alias="m", include_global=include_global)
                where = where.replace("?", "%s")
                cur.execute(
                    f"SELECT m.id, m.tags FROM memories m WHERE {where}",
                    tuple(scope_params),
                )
            else:
                cur.execute(
                    "SELECT id, tags FROM memories WHERE COALESCE(status, 'active') = 'active'"
                )
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
                have = set(tlist)
                matches = wanted <= have if match in {"all", "strict"} else bool(wanted & have)
                if matches:
                    ids.add(int(d.get("id") or row[0]))
            return ids
        except Exception:  # noqa: BLE001
            return set()

    def close(self) -> None:
        try:
            self.conn.close()
        except (AttributeError, OSError, RuntimeError):
            pass
