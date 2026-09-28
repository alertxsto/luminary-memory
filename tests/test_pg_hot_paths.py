"""Resource bounds and real-database behavior of PostgreSQL retrieval/maintenance."""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from luminary_memory.backends.pgvector import PGVectorBackend
from luminary_memory.recall.temporal import temporal_recall
from luminary_memory.types import Memory


class _CountingCursor:
    def __init__(self, cursor, owner):
        self.cursor = cursor
        self.owner = owner

    def execute(self, *args, **kwargs):
        self.owner.queries += 1
        return self.cursor.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class _CountingConnection:
    def __init__(self, conn):
        self.conn = conn
        self.queries = 0
        self.commits = 0

    def cursor(self):
        return _CountingCursor(self.conn.cursor(), self)

    def commit(self):
        self.commits += 1
        return self.conn.commit()

    def __getattr__(self, name):
        return getattr(self.conn, name)


class _CountingCursor:
    def __init__(self, cursor, owner):
        self.cursor = cursor
        self.owner = owner

    def execute(self, *args, **kwargs):
        self.owner.queries += 1
        return self.cursor.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class _CountingConnection:
    def __init__(self, conn):
        self.conn = conn
        self.queries = 0
        self.commits = 0

    def cursor(self):
        return _CountingCursor(self.conn.cursor(), self)

    def commit(self):
        self.commits += 1
        return self.conn.commit()

    def __getattr__(self, name):
        return getattr(self.conn, name)


class _CandidateCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rows = []

    def execute(self, sql, params=None):
        self.conn.queries.append((sql, params))
        normalized = " ".join(sql.split())
        if "SELECT m.id, COALESCE(m.observed_at, m.created_at)" in normalized:
            # This fixture models the database predicate, not the backend's
            # implementation: reject SQL that transfers full rows or allows
            # a foreign/expired candidate into top-k.
            assert "m.metadata" not in sql and "m.embedding" not in sql and "SELECT *" not in sql
            assert "m.user_id" in sql and "m.workspace_id" in sql
            assert "m.status" in sql and "m.valid_from" in sql and "m.valid_to" in sql
            assert "CURRENT_TIMESTAMP" in sql
            assert params == ("alice", "work")
            self.rows = [
                (r["id"], r["observed_at"] or r["created_at"], r["access_count"])
                for r in self.conn.memories
        {"id": 1, "content": "foreign newest", "user_id": "bob", "workspace_id": "work",
         "status": "active", "created_at": now, "observed_at": None, "access_count": 0,
         "valid_from": None, "valid_to": None},
        {"id": 2, "content": "expired", "user_id": "alice", "workspace_id": "work",
         "status": "active", "created_at": now, "observed_at": None, "access_count": 0,
         "valid_from": None, "valid_to": now - timedelta(hours=1)},
        {"id": 3, "content": "future", "user_id": "alice", "workspace_id": "work",
         "status": "active", "created_at": now, "observed_at": None, "access_count": 0,
         "valid_from": now + timedelta(hours=1), "valid_to": None},
        {"id": 4, "content": "superseded", "user_id": "alice", "workspace_id": "work",
         "status": "superseded", "created_at": now, "observed_at": None, "access_count": 0,
         "valid_from": None, "valid_to": None},
        {"id": 5, "content": "older", "user_id": "alice", "workspace_id": "work",
         "status": "active", "created_at": now - timedelta(hours=48),
         "observed_at": now - timedelta(hours=48), "access_count": 0,
         "valid_from": None, "valid_to": None},
        {"id": 6, "content": "observed recently", "user_id": "alice", "workspace_id": "work",
         "status": "active", "created_at": now - timedelta(days=10),
         "observed_at": now - timedelta(hours=1), "access_count": 0,
         "valid_from": None, "valid_to": None},
        elif "SELECT * FROM memories" in normalized:
            assert "ANY(%s)" in sql
            self.rows = [r for r in self.conn.memories if r["id"] in params[0]]
        else:
            raise AssertionError(f"unexpected database query: {sql}")
        return self

    def fetchall(self):
        return self.rows


class _CandidateConn:
    def __init__(self, memories, now):
        self.memories = memories
        self.now = now
    foreign = {
        "id": 1, "content": "other tenant", "user_id": "bob", "workspace_id": "work",
        "status": "active", "created_at": now, "observed_at": None, "access_count": 0,
        "valid_from": None, "valid_to": None,
    }

def test_temporal_scans_only_scoped_valid_candidates_and_hydrates_top_k_once():
    now = datetime.now(UTC)
    rows = [
        dict(id=1, content="foreign newest", user_id="bob", workspace_id="work", status="active", created_at=now, observed_at=None, access_count=0, valid_from=None, valid_to=None),
        dict(id=2, content="expired", user_id="alice", workspace_id="work", status="active", created_at=now, observed_at=None, access_count=0, valid_from=None, valid_to=now - timedelta(hours=1)),
        dict(id=3, content="future", user_id="alice", workspace_id="work", status="active", created_at=now, observed_at=None, access_count=0, valid_from=now + timedelta(hours=1), valid_to=None),
        dict(id=4, content="superseded", user_id="alice", workspace_id="work", status="superseded", created_at=now, observed_at=None, access_count=0, valid_from=None, valid_to=None),
        dict(id=5, content="older", user_id="alice", workspace_id="work", status="active", created_at=now - timedelta(hours=48), observed_at=now - timedelta(hours=48), access_count=0, valid_from=None, valid_to=None),
        dict(id=6, content="observed recently", user_id="alice", workspace_id="work", status="active", created_at=now - timedelta(days=10), observed_at=now - timedelta(hours=1), access_count=0, valid_from=None, valid_to=None),
    ]
    b = PGVectorBackend.__new__(PGVectorBackend)
    b.conn = _CandidateConn(rows, now)
    hits = temporal_recall(b, limit=2, scope={"user_id": "alice", "workspace_id": "work"}, include_global=False)
    assert [(m.id, m.content, label) for m, _, label in hits] == [
        (6, "observed recently", "temporal"), (5, "older", "temporal")
    ]
    assert hits[0][1] > hits[1][1]
    assert len(b.conn.queries) == 2
    assert len(b.conn.queries[1][1][0]) == 2
    assert b.get_many([]) == {}
    assert len(b.conn.queries) == 2

def test_scoped_temporal_scan_empty_does_not_fall_back_to_full_rows():
    now = datetime.now(UTC)
    foreign = dict(
        id=1, content="other tenant", user_id="bob", workspace_id="work",
        status="active", created_at=now, observed_at=None, access_count=0,
        valid_from=None, valid_to=None,
    )
    b = PGVectorBackend.__new__(PGVectorBackend)
    b.conn = _CandidateConn([foreign], now)
    assert temporal_recall(
        quote = unique + " source quote"
        b.add_evidence(ids[0], quote)
        b.add_claim(ids[0], {"subject": unique, "predicate": "uses", "object": "PG", "evidence_quote": quote}, user_id=unique)
    ) == []
    assert len(b.conn.queries) == 1


        traced = _CountingConnection(b.conn)
        b.conn = traced
        # The scan is intentionally not ordered by SQL; ranking happens
        # after all valid candidates have been read.
        scan = b.temporal_scan(scope={"user_id": unique, "workspace_id": "integration"}, include_global=False, include_observed=True)
        assert {row[0] for row in scan} == set(ids[:4])
        assert len(scan[0]) == 3
        assert traced.queries == 1
        hydrated = b.get_many([ids[3], ids[0], ids[3], -1])
        assert list(hydrated) == [ids[0], ids[3]]
        assert hydrated[ids[0]].content.endswith(" 0")
        assert traced.queries == 2
        before = [b.get(mid).access_count for mid in ids[:4]]
        traced.queries = 0
        b.touch_memories([*ids[:4], ids[0], -1])
        assert (traced.queries, traced.commits) == (1, 1)
        assert [b.get(mid).access_count for mid in ids[:4]] == [n + 1 for n in before]
        assert all(b.get(mid).last_accessed_at for mid in ids[:4])
        traced.queries = 0
        b.delete_many([ids[0], ids[1], -1, ids[0]])
        assert (traced.queries, traced.commits) == (2, 2)
    assert len(b.conn.queries) == 1


@pytest.mark.skipif(
    not (os.environ.get("LUMINARY_PG_DSN") or os.environ.get("PG_DSN")),
    reason="no PostgreSQL DSN (LUMINARY_PG_DSN / PG_DSN)",
                        (unique if table == "claims" else quote,))
def test_pg_hot_paths_live_roundtrips_and_fk_semantics():
    dsn = os.environ.get("LUMINARY_PG_DSN") or os.environ["PG_DSN"]
    b = PGVectorBackend(dsn=dsn, embedding_dim=384)
    finally:
        try:
            b.delete_many(ids)
            cur = b.conn.cursor()
            cur.execute(
                "DELETE FROM claim_evidence WHERE claim_id IN "
                "(SELECT id FROM claims WHERE subject = %s)", (unique,)
            )
            cur.execute("DELETE FROM claims WHERE subject = %s", (unique,))
            cur.execute("DELETE FROM memory_evidence WHERE quote = %s", (unique + " source quote",))
            cur.execute("DELETE FROM entities WHERE name IN (%s, %s)", (unique + " a", unique + " b"))
            b.conn.commit()
        finally:
            b.close()
    try:
        for idx in range(5):
            ids.append(b.add(Memory(
                workspace_id="integration", embedding=[0.0] * 384,
                created_at=(now - timedelta(hours=idx)).isoformat(),
                observed_at=(now - timedelta(hours=idx)).isoformat(),
                valid_to=(now - timedelta(minutes=1)).isoformat() if idx == 4 else None,
            )))
        cur = b.conn.cursor()
        cur.execute("INSERT INTO entities (name) VALUES (%s), (%s) RETURNING id", (unique + " a", unique + " b"))
        entity_a, entity_b = (r[0] for r in cur.fetchall())
        cur.execute("INSERT INTO relations (source_id, target_id, memory_id) VALUES (%s, %s, %s)", (entity_a, entity_b, ids[0]))
        b.add_evidence(ids[0], "source quote")
        b.add_claim(ids[0], {"subject": unique, "predicate": "uses", "object": "PG", "evidence_quote": "source quote"}, user_id=unique)
        for table, col in (("relations", "memory_id"), ("claims", "memory_id"), ("memory_evidence", "memory_id"), ("claim_evidence", "claim_id")):
            cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (f"idx_{table}_{col}",))
            assert cur.fetchone() is not None
        b.conn.commit()

        # psycopg trace callback counts executed statements, including the
        # The scan is intentionally not ordered by SQL; ranking happens
        # after all valid candidates have been read.
        scan = b.temporal_scan(scope={"user_id": unique, "workspace_id": "integration"}, include_global=False, include_observed=True)
        assert {row[0] for row in scan} == set(ids[:4])
        hydrated = b.get_many([ids[3], ids[0], ids[3], -1])
        assert list(hydrated) == [ids[0], ids[3]]
        assert hydrated[ids[0]].content.endswith(" 0")
        before = [b.get(mid).access_count for mid in ids[:4]]
        b.touch_memories([*ids[:4], ids[0], -1])
        assert [b.get(mid).access_count for mid in ids[:4]] == [n + 1 for n in before]
        assert all(b.get(mid).last_accessed_at for mid in ids[:4])
        b.delete_many([ids[0], ids[1], -1, ids[0]])
        assert b.get_many(ids[:2]) == {}
        cur.execute("SELECT COUNT(*) FROM relations WHERE memory_id = %s", (ids[0],))
        assert cur.fetchone()[0] == 0
        for table in ("claims", "memory_evidence"):
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE memory_id IS NULL AND "
                        + ("subject = %s" if table == "claims" else "quote = %s"),
                        (unique if table == "claims" else "source quote",))
            assert cur.fetchone()[0] >= 1
        cur.execute("SELECT COUNT(*) FROM claim_evidence ce JOIN claims c ON c.id = ce.claim_id WHERE c.subject = %s", (unique,))
        assert cur.fetchone()[0] >= 1
    finally:
        b.delete_many(ids)
        b.close()




class _SQLitePgCursor:
    """Execute the batch SQL against SQLite's real FK/row engine."""

    def __init__(self, conn):
        self.conn = conn
        self.cur = conn.db.cursor()

    def execute(self, sql, params=None):
        assert sql.count("= ANY(%s)") <= 1
        if "= ANY(%s)" in sql:
            ids = params[0]
            sql = sql.replace("= ANY(%s)", f"IN ({','.join('?' for _ in ids)})")
            params = ids
        else:
            sql = sql.replace("%s", "?")
        self.cur.execute(sql, params or ())
        self.cur.execute(sql, params or ())
        return self

    def fetchall(self):
        return [dict(row) for row in self.cur.fetchall()]


class _SQLitePgConn:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE memories (id INTEGER PRIMARY KEY, content TEXT, access_count INTEGER DEFAULT 0,
                last_accessed_at TEXT, created_at TEXT);
            CREATE TABLE relations (memory_id INTEGER REFERENCES memories(id));
            CREATE TABLE memory_evidence (memory_id INTEGER REFERENCES memories(id) ON DELETE SET NULL, quote TEXT);
            CREATE TABLE claims (id INTEGER PRIMARY KEY, memory_id INTEGER REFERENCES memories(id) ON DELETE SET NULL);
            CREATE TABLE claim_evidence (claim_id INTEGER REFERENCES claims(id) ON DELETE SET NULL);
        """)
        self.queries = []
        self.commits = 0

    def cursor(self):


def test_batch_delete_rolls_back_relation_cleanup_if_memory_delete_fails():
    b = PGVectorBackend.__new__(PGVectorBackend)
    b.conn = _SQLitePgConn()
    db = b.conn.db
    db.executemany("INSERT INTO memories(id, content) VALUES (?, ?)", [(1, "one"), (2, "two")])
    db.execute("INSERT INTO relations(memory_id) VALUES (1)")
    db.execute("""
        CREATE TRIGGER reject_delete BEFORE DELETE ON memories
        WHEN OLD.id = 2 BEGIN SELECT RAISE(ABORT, 'blocked'); END
    """)
    db.commit()
    with pytest.raises(sqlite3.DatabaseError, match="blocked"):
        b.delete_many([1, 2])
    assert [r[0] for r in db.execute("SELECT id FROM memories ORDER BY id")] == [1, 2]
    assert db.execute("SELECT memory_id FROM relations").fetchone()[0] == 1
    assert b.conn.commits == 0
        return _SQLitePgCursor(self)

    def commit(self):
        self.db.commit()
        self.commits += 1

    def rollback(self):
        self.db.rollback()


def test_batch_get_delete_touch_bound_roundtrips_and_keep_history():
    b = PGVectorBackend.__new__(PGVectorBackend)
    b.conn = _SQLitePgConn()
    db = b.conn.db
    db.executemany("INSERT INTO memories(id, content, created_at) VALUES (?, ?, ?)", [
        (1, "one", "2026-01-01"), (2, "two", "2026-01-02"), (3, "three", "2026-01-03")
    ])
    db.execute("INSERT INTO relations(memory_id) VALUES (1)")
    db.execute("INSERT INTO memory_evidence(memory_id, quote) VALUES (1, 'retained')")
    db.execute("INSERT INTO claims(id, memory_id) VALUES (9, 1)")
    db.execute("INSERT INTO claim_evidence(claim_id) VALUES (9)")
    assert b.get_many([]) == {}
    assert b.conn.queries == []
    found = b.get_many([2, -1, 1, 2])
    assert list(found) == [1, 2]
    assert [found[i].content for i in (1, 2)] == ["one", "two"]
    assert len(b.conn.queries) == 1
    assert [b.get_many([2, 1])[i].content for i in (1, 2)] == ["one", "two"]
    b.conn.queries.clear()
    b.touch_memories([])
    b.touch_memories([1, 2, 1, -1])
    assert len(b.conn.queries) == 1
    assert b.conn.commits == 1
    assert [(r["access_count"], bool(r["last_accessed_at"])) for r in
            db.execute("SELECT access_count,last_accessed_at FROM memories ORDER BY id")] == [
                (1, True), (1, True), (0, False)
            ]
    b.conn.queries.clear()
    b.delete_many([])
    b.delete_many([1, 2, 1, -1])
    assert len(b.conn.queries) == 2
    assert b.conn.commits == 2
    assert [r["id"] for r in db.execute("SELECT id FROM memories")] == [3]
    assert list(db.execute("SELECT memory_id FROM relations")) == []
    assert db.execute("SELECT memory_id FROM memory_evidence").fetchone()[0] is None
    assert db.execute("SELECT memory_id FROM claims").fetchone()[0] is None
    assert db.execute("SELECT claim_id FROM claim_evidence").fetchone()[0] == 9
