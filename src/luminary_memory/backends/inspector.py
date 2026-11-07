"""Shared SQL primitives for inspector metadata and atomic engine writers.

A store-wide transaction lock deliberately serializes claim-set membership changes.
It also covers batches touching several claim domains, avoiding advisory-lock order
inversions. SQLite uses its writer lock; PostgreSQL uses a transaction advisory lock.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from functools import wraps

from luminary_memory.types import utc_timestamp


class ContentRevisionConflict(RuntimeError):
    """A normal engine writer attempted to replace a newer content revision."""


def atomic_backend(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.transaction():
            return method(self, *args, **kwargs)
    return wrapped


def atomic_client(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.backend.transaction():
            return method(self, *args, **kwargs)
    return wrapped


class InspectorSQL:
    """Backend-only SQL: never exposed to a renderer or request-supplied SQL."""

    @property
    def in_transaction(self):
        return bool(getattr(self._local, "transaction_depth", 0))

    def _check_revision(self, memory):
        current = self.get(memory.id)
        if current is None or current.revision != memory.revision:
            raise ContentRevisionConflict("content revision changed")

    def _refresh_revision(self, memory):
        memory.revision = self.get(memory.id).revision


    def _commit(self):
        if not self.in_transaction:
            self.conn.commit()

    def _rollback(self):
        if not self.in_transaction:
            self.conn.rollback()

    def _sql(self, sql, params=()):
        if hasattr(self, "_psycopg"):
            return self.conn.execute(sql.replace("?", "%s"), params)
        return self.conn.execute(sql, params)

    def _inspector_table(self, name):
        """Pin inspector reads to this store instead of a search-path fallback."""
        if hasattr(self, "_psycopg"):
            return self._psycopg.sql.Identifier(self._namespace, name).as_string(self.conn)
        return '"main"."' + name.replace('"', '""') + '"'

    def find_import_duplicate_id(self, memory):
        """Reuse an identical stored observation, never a new historical occurrence."""
        created = utc_timestamp(memory.created_at)
        if not memory.content_hash or created is None:
            return None
        clauses, values = [], []
        for field in ("user_id", "workspace_id", "agent_id", "session_id", "source_id"):
            value = getattr(memory, field)
            if value is None or value == "":
                clauses.append(f"({field} IS NULL OR {field}='')")
            else:
                clauses.append(f"{field}=?")
                values.append(value)
        timestamp = "created_at" if hasattr(self, "_psycopg") else "inspector_utc(created_at)"
        clauses.extend(("content_hash=?", "status=?", f"{timestamp}=?"))
        values.extend((memory.content_hash, memory.status, created))
        if memory.supersedes_id is None:
            clauses.append("supersedes_id IS NULL")
        else:
            clauses.append("supersedes_id=?")
            values.append(memory.supersedes_id)
        row = self._sql(f"SELECT id FROM {self._inspector_table('memories')} WHERE "
                        + " AND ".join(clauses) + " ORDER BY id LIMIT 1", values).fetchone()
        return int(row[0]) if row else None

    @contextmanager
    def transaction(self):
        if self.in_transaction:
            self._local.transaction_depth += 1
            try:
                yield self
            finally:
                self._local.transaction_depth -= 1
            return
        conn = self.conn
        conn.execute("BEGIN" if hasattr(self, "_psycopg") else "BEGIN IMMEDIATE")
        self._local.transaction_depth = 1
        try:
            self.lock_claim_set({}, None)
            yield self
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            self._local.transaction_depth = 0

    def lock_claim_set(self, scope, claim_key):
        """Hold the same lock used by every normal content/claim writer.

        Coarse by design: domains and scopes cannot race membership rechecks,
        and a multi-domain supersession never takes locks in opposing order.
        """
        if not self.in_transaction:
            raise RuntimeError("claim-set locking requires a transaction")
        if hasattr(self, "_psycopg"):
            self._sql("SELECT pg_advisory_xact_lock(718946072154113)")

    def _inspector_schema(self):
        self._sql("CREATE TABLE IF NOT EXISTS inspector_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        fields = ("content", "metadata", "source", "tags", "ttl_seconds", "user_id",
                  "session_id", "workspace_id", "agent_id", "observed_at", "valid_from",
                  "valid_to", "status", "confidence", "evidence_quote", "source_id",
                  "claim_key", "supersedes_id")
        if hasattr(self, "_psycopg"):
            old = ",".join("OLD." + field for field in fields)
            new = ",".join("NEW." + field for field in fields)
            self._sql("CREATE OR REPLACE FUNCTION luminary_content_revision() RETURNS trigger AS $$ "
                      "BEGIN IF ROW(" + old + ") IS DISTINCT FROM ROW(" + new + ") THEN "
                      "NEW.revision := OLD.revision + 1; ELSE NEW.revision := OLD.revision; "
                      "END IF; RETURN NEW; END; $$ LANGUAGE plpgsql")
            self._sql("CREATE OR REPLACE TRIGGER memories_content_revision BEFORE UPDATE ON memories "
                      "FOR EACH ROW EXECUTE FUNCTION luminary_content_revision()")
        else:
            changed = " OR ".join("OLD." + field + " IS NOT NEW." + field for field in fields)
            self._sql("CREATE TRIGGER IF NOT EXISTS memories_content_revision AFTER UPDATE ON memories "
                      "WHEN " + changed + " BEGIN UPDATE memories SET revision=OLD.revision+1 "
                      "WHERE id=NEW.id; END")
        existing = set()
        if not hasattr(self, "_psycopg"):
            existing = {row[1] for row in self._sql("PRAGMA table_info(memory_events)").fetchall()}
        for field in ("user_id", "workspace_id", "agent_id", "session_id"):
            if hasattr(self, "_psycopg"):
                self._sql(f"ALTER TABLE memory_events ADD COLUMN IF NOT EXISTS {field} TEXT")
            elif field not in existing:
                self._sql(f"ALTER TABLE memory_events ADD COLUMN {field} TEXT")
        self._sql("CREATE INDEX IF NOT EXISTS idx_memory_events_scope ON memory_events(user_id,workspace_id,agent_id,id)")
        self._commit()

    def _record_scoped_event(self, event_type, memory_id, before=None, after=None, actor=None):
        fields = ("user_id", "workspace_id", "agent_id", "session_id")
        live = self.get(memory_id) if memory_id is not None else None
        scope = {field: getattr(live, field) for field in fields} if live else None
        for snapshot in (before, after):
            if snapshot is None:
                continue
            if scope is None and all(field in snapshot for field in fields[:3]):
                scope = {field: snapshot.get(field) for field in fields}
            if scope is not None and any(field in snapshot and snapshot[field] != scope[field] for field in fields):
                raise PermissionError("audit snapshot scope disagrees with resource ownership")
        scope = scope or dict.fromkeys(fields)
        json_placeholder = "?::jsonb" if hasattr(self, "_psycopg") else "?"
        self._sql("INSERT INTO memory_events(memory_id,event_type,before_json,after_json,actor,"
                  "user_id,workspace_id,agent_id,session_id) VALUES (?,?," + json_placeholder + "," +
                  json_placeholder + ",?,?,?,?,?)",
                  (memory_id, event_type, json.dumps(before) if before is not None else None,
                   json.dumps(after) if after is not None else None, actor,
                   *(scope[field] for field in fields)))
        self._commit()

    def inspector_get(self, key, default=None):
        row = self._sql("SELECT value FROM inspector_metadata WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def inspector_put(self, key, value):
        self._sql("INSERT INTO inspector_metadata(key,value) VALUES (?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, json.dumps(value, sort_keys=True, separators=(",", ":"))))
        self._commit()

    def inspector_remove(self, key):
        self._sql("DELETE FROM inspector_metadata WHERE key=?", (key,))
        self._commit()

    def inspector_scan(self, prefix):
        rows = self._sql("SELECT key,value FROM inspector_metadata WHERE key LIKE ? ORDER BY key", (prefix + "%",)).fetchall()
        return [(row[0], json.loads(row[1])) for row in rows]

    def inspector_memories(self, scopes, *, statuses=None, tags=None, query=None,
                           created_after=None, created_before=None, after=None, limit=101):
        """Apply exact authorized resource scopes before ordering and limits."""
        if not scopes:
            return []
        clauses, params = [], []
        for scope in scopes:
            clauses.append("(m.user_id=? AND m.workspace_id=? AND m.agent_id=?)")
            params.extend(scope[field] for field in ("user_id", "workspace_id", "agent_id"))
        where = ["(" + " OR ".join(clauses) + ")"]
        if statuses:
            where.append("m.status IN (" + ",".join("?" for _ in statuses) + ")")
            params.extend(statuses)
        if query:
            where.append("LOWER(m.content) LIKE ? ESCAPE '\\'")
            params.append("%" + query.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        for tag in tags or []:
            if hasattr(self, "_psycopg"):
                where.append("m.tags @> ?::jsonb")
                params.append(json.dumps([tag]))
            else:
                where.append("EXISTS(SELECT 1 FROM json_each(m.tags) WHERE value=?)")
                params.append(tag)
        if created_after:
            where.append("m.created_at >= ?")
            params.append(created_after)
        if created_before:
            where.append("m.created_at <= ?")
            params.append(created_before)
        if after:
            where.append("(m.created_at < ? OR (m.created_at = ? AND m.id < ?))")
            params.extend((after[0], after[0], after[1]))
        params.append(limit)
        rows = self._sql("SELECT m.* FROM memories m WHERE " + " AND ".join(where) +
                         " ORDER BY m.created_at DESC,m.id DESC LIMIT ?", params).fetchall()
        return [self._row_to_memory(row) for row in rows]

    def inspector_provenance(self, memory_id, *, limit=5):
        memory = self.get(memory_id)
        if memory is None:
            return {"evidence": [], "claims": []}
        evidence = self._sql("SELECT id,quote,observed_at,extractor,confidence FROM memory_evidence "
                             "WHERE memory_id=? ORDER BY id DESC LIMIT ?", (memory_id, limit)).fetchall()
        claims = self._sql("SELECT id,subject,predicate,object,polarity,status,confidence,evidence_quote "
                           "FROM claims WHERE memory_id=? AND user_id=? AND workspace_id=? AND agent_id=? "
                           "ORDER BY id DESC LIMIT ?", (memory_id, memory.user_id, memory.workspace_id, memory.agent_id, limit)).fetchall()
        return {
            "evidence": [dict(zip(("id", "quote", "observed_at", "extractor", "confidence"), row)) for row in evidence],
            "claims": [dict(zip(("id", "subject", "predicate", "object", "polarity", "status", "confidence", "evidence_quote"), row)) for row in claims],
        }

    def inspector_events(self, scopes, *, memory_id=None, after=None, limit=101, exclude_kinds=()):
        # Persisted event scope survives deletion. Unverified legacy rows with
        # missing scope are intentionally not attributed from mutable live rows.
        if not scopes:
            return []
        predicates, params = [], []
        for scope in scopes:
            predicates.append("(e.user_id=? AND e.workspace_id=? AND e.agent_id=?)")
            params.extend(scope[field] for field in ("user_id", "workspace_id", "agent_id"))
        where = ["(" + " OR ".join(predicates) + ")"]
        if memory_id is not None:
            where.append("e.memory_id=?")
            params.append(memory_id)
        if after is not None:
            where.append("e.id < ?")
            params.append(after)
        if exclude_kinds:
            where.append("e.event_type NOT IN (" + ",".join("?" for _ in exclude_kinds) + ")")
            params.extend(exclude_kinds)
        params.append(limit)
        rows = self._sql("SELECT e.id,e.memory_id,e.event_type,e.created_at,e.before_json,e.after_json,e.actor "
                         "FROM memory_events e WHERE " +
                         " AND ".join(where) + " ORDER BY e.id DESC LIMIT ?", params).fetchall()
        return [dict(zip(("event_id", "memory_id", "kind", "created_at", "before", "after", "actor"), row)) for row in rows]

    def inspector_lineage(self, scopes, memory):
        if not scopes:
            return []
        predicates, params = [], []
        for scope in scopes:
            predicates.append("(m.user_id=? AND m.workspace_id=? AND m.agent_id=?)")
            params.extend(scope[field] for field in ("user_id", "workspace_id", "agent_id"))
        params.extend((memory.supersedes_id, memory.id))
        rows = self._sql("SELECT m.id,m.supersedes_id,m.status,m.revision FROM memories m WHERE (" +
                         " OR ".join(predicates) + ") AND (m.id=? OR m.supersedes_id=?) ORDER BY m.id LIMIT 100", params).fetchall()
        return [dict(zip(("id", "supersedes_id", "status", "revision"), row)) for row in rows]

    @atomic_backend
    def touch_memories(self, ids):
        if not ids:
            return
        for start in range(0, len(ids), 450):
            chunk = ids[start:start + 450]
            self._sql("UPDATE memories SET access_count=access_count+1,last_accessed_at=CURRENT_TIMESTAMP "
                      "WHERE id IN (" + ",".join("?" for _ in chunk) + ")", chunk)

    @atomic_backend
    def update_importance_many(self, updates):
        for importance, memory_id in updates:
            self._sql("UPDATE memories SET importance=? WHERE id=?", (importance, memory_id))

    def inspector_claim_set(self, memory):
        rows = self._sql("SELECT c.id,c.memory_id,c.status,c.subject,c.predicate,c.object,c.polarity,c.confidence "
                         "FROM claims c JOIN memories m ON m.id=c.memory_id WHERE "
                         "c.user_id=? AND c.workspace_id=? AND c.agent_id=? AND "
                         "m.user_id=? AND m.workspace_id=? AND m.agent_id=? AND "
                         "(m.claim_key=? OR LOWER(c.subject)||'|'||LOWER(c.predicate)||'|'||LOWER(c.polarity)=?) "
                         "AND c.status IN ('active','conflicted') ORDER BY c.id",
                         (memory.user_id, memory.workspace_id, memory.agent_id,
                          memory.user_id, memory.workspace_id, memory.agent_id, memory.claim_key, memory.claim_key)).fetchall()
        return [list(row) for row in rows]

    def inspector_episodes(self, memory, *, limit=10):
        rows = self._sql("SELECT DISTINCT e.id,e.content,e.observed_at,e.created_at FROM episodes e "
                         "WHERE e.user_id=? AND e.workspace_id=? AND e.agent_id=? AND "
                         "(e.id=? OR e.id IN (SELECT source_episode_id FROM claims WHERE memory_id=? "
                         "AND user_id=? AND workspace_id=? AND agent_id=?)) "
                         "ORDER BY e.created_at DESC,e.id DESC LIMIT ?",
                         (memory.user_id, memory.workspace_id, memory.agent_id, f"memory:{memory.id}", memory.id,
                          memory.user_id, memory.workspace_id, memory.agent_id, limit)).fetchall()
        return [dict(zip(("id", "content", "observed_at", "created_at"), row)) for row in rows]
