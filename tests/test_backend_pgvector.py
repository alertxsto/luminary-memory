import os
from unittest.mock import patch

import pytest

from luminary_memory.types import Memory

_SKIP_MSG = "no pgvector DSN / PostgreSQL not available"


def _pg_available() -> bool:
    dsn = os.environ.get("LUMINARY_PG_DSN", os.environ.get("PG_DSN", ""))
    if not dsn:
        return False
    try:
        import psycopg  # noqa: F401
    except ImportError:
        return False
    return True


class _FakeCursor:
    def __init__(self):
        self.executed: list[tuple] = []
        self._rows: list[tuple] = []
        self._one = None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return self

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self):
        self.cur = _FakeCursor()
        self.committed = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed += 1

    def close(self):
        pass


@pytest.mark.skipif(not _pg_available(), reason=_SKIP_MSG)
def test_pg_integration_smoke():
    """Real Postgres round-trip: create schema, add, get, search, delete."""
    dsn = os.environ.get("LUMINARY_PG_DSN", os.environ.get("PG_DSN", ""))
    if not dsn:
        pytest.skip(_SKIP_MSG)
    from luminary_memory.backends.pgvector import PGVectorBackend

    b = PGVectorBackend(dsn=dsn, embedding_dim=384)
    try:
        m = Memory(content="integration smoke test memory", tags=["smoke"])
        m.embedding = [0.0] * 384
        mid = b.add(m)
        assert mid is not None
        got = b.get(mid)
        assert got is not None and got.content == "integration smoke test memory"
        assert b.count() >= 1
        hits = b.keyword_search("smoke", limit=5)
        assert any(h[0].content == "integration smoke test memory" for h in hits)
        b.delete(mid)
        assert b.get(mid) is None
    finally:
        b.close()


@pytest.mark.skipif(not _pg_available(), reason=_SKIP_MSG)
def test_pg_integration_mutations_tags_and_hnsw():
    """Exercise real Postgres mutations, JSONB round-trips, tags, and HNSW setup."""
    dsn = os.environ.get("LUMINARY_PG_DSN", os.environ.get("PG_DSN", ""))
    from luminary_memory.backends.pgvector import PGVectorBackend

    b = PGVectorBackend(dsn=dsn, embedding_dim=384, hnsw=True)
    ids: list[int] = []
    try:
        cur = b.conn.cursor()
        cur.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'memories' AND indexname = 'memories_embedding_hnsw'"
        )
        assert cur.fetchone() is not None

        memories = [
            Memory(
                content="batch alpha",
                metadata={"kind": "alpha"},
                tags=["ci", "alpha"],
                embedding=[0.0] * 384,
            ),
            Memory(
                content="batch beta",
                metadata={"kind": "beta"},
                tags=["ci", "beta"],
                embedding=[1.0] + [0.0] * 383,
            ),
        ]
        ids = b.add_many(memories)
        assert len(ids) == 2 and all(ids)

        first = b.get(ids[0])
        assert first is not None
        assert first.metadata == {"kind": "alpha"}
        assert first.tags == ["ci", "alpha"]

        first.content = "batch alpha updated"
        first.metadata = {"kind": "updated"}
        first.tags = ["ci", "updated"]
        first.embedding = [0.0] * 384
        b.update(first)
        updated = b.get(ids[0])
        assert updated is not None
        assert updated.content == "batch alpha updated"
        assert updated.metadata == {"kind": "updated"}
        assert updated.tags == ["ci", "updated"]

        assert ids[0] in b.by_tags(["updated"])
        assert ids[1] in b.by_tags(["beta"])
        b.delete(ids[1])
        assert b.get(ids[1]) is None
    finally:
        for memory_id in ids:
            b.delete(memory_id)
        b.close()


@pytest.mark.skipif(not _pg_available(), reason=_SKIP_MSG)
def test_pg_integration_add_many_rolls_back_on_failure():
    """A failed batch must not leave earlier rows committed in Postgres."""
    dsn = os.environ.get("LUMINARY_PG_DSN", os.environ.get("PG_DSN", ""))
    from psycopg.errors import NotNullViolation

    from luminary_memory.backends.pgvector import PGVectorBackend

    b = PGVectorBackend(dsn=dsn, embedding_dim=384)
    try:
        baseline = b.count()
        valid = Memory(content="should roll back", embedding=[0.0] * 384)
        invalid = Memory(content=None, embedding=[0.0] * 384)  # type: ignore[arg-type]
        with pytest.raises(NotNullViolation):
            b.add_many([valid, invalid])
        assert b.count() == baseline
    finally:
        b.close()


def test_pgvector_backend_unit_add_encodes_embedding():
    with patch("psycopg.connect") as mock_connect:
        from luminary_memory.backends.pgvector import PGVectorBackend

        fake = _FakeConn()
        fake.cur._one = (42,)
        mock_connect.return_value = fake
        b = PGVectorBackend(dsn="postgresql://localhost/x", embedding_dim=3)
        committed_after_init = fake.committed
        mid = b.add(Memory(content="hello embedding test", embedding=[0.1, 0.2, 0.3]))
        assert mid == 42
        assert fake.committed == committed_after_init + 1


def test_pgvector_keyword_search_builds_ilike_query():
    with patch("psycopg.connect") as mock_connect:
        from luminary_memory.backends.pgvector import PGVectorBackend

        fake = _FakeConn()
        fake.cur._rows = []
        mock_connect.return_value = fake
        b = PGVectorBackend(dsn="postgresql://localhost/x", embedding_dim=3)
        res = b.keyword_search("hello world", limit=5)
        assert res == []
        sql = fake.cur.executed[-1][0]
        assert "ILIKE" in sql


def test_pgvector_vector_search_uses_cosine_operator():
    with patch("psycopg.connect") as mock_connect:
        from luminary_memory.backends.pgvector import PGVectorBackend

        fake = _FakeConn()
        fake.cur._rows = []
        mock_connect.return_value = fake
        b = PGVectorBackend(dsn="postgresql://localhost/x", embedding_dim=3)
        res = b.vector_search([1.0, 0.0, 0.0], limit=3)
        assert res == []
        sql = fake.cur.executed[-1][0]
        assert "<=>" in sql


def test_backend_factory_returns_sqlite_by_default():
    from luminary_memory.backends import get_backend
    from luminary_memory.config import Settings

    b = get_backend(Settings(backend="sqlite", db_path=":memory:"))
    assert b.__class__.__name__ == "SQLiteBackend"
    b.close()


def test_backend_factory_returns_pgvector_when_configured():
    from luminary_memory.backends import get_backend
    from luminary_memory.config import Settings

    with patch("psycopg.connect"):
        b = get_backend(Settings(backend="pgvector", pg_dsn="postgresql://localhost/x"))
        assert b.__class__.__name__ == "PGVectorBackend"
        b.close()


def test_api_uses_factory_when_no_backend_injected(tmp_path):
    from luminary_memory.api import MemoryClient
    from luminary_memory.config import Settings

    class FakeE:
        def embed(self, t): return [0.1] * 384

    settings = Settings(backend="sqlite", db_path=str(tmp_path / "a.db"))
    c = MemoryClient(settings=settings, engine=FakeE())
    assert c.backend.__class__.__name__ == "SQLiteBackend"
    c.close()
    c2 = MemoryClient(db_path=str(tmp_path / "b.db"), engine=FakeE())
    assert c2.backend.__class__.__name__ == "SQLiteBackend"
    c2.close()


def test_pgvector_get_row_parsing():
    """get() must parse a real-ish row (dict) into a Memory."""
    with patch("psycopg.connect") as mock_connect:
        from luminary_memory.backends.pgvector import PGVectorBackend

        fake = _FakeConn()
        fake.cur._one = {
            "id": 7,
            "content": "parsed content",
            "metadata": '{"summary": "x"}',
            "source": "test",
            "tags": '["a","b"]',
            "importance": 0.9,
            "ttl_seconds": None,
            "created_at": "2026-08-17T00:00:00+00:00",
            "updated_at": "2026-08-17T00:00:00+00:00",
            "last_accessed_at": None,
            "access_count": 3,
            "embedding": "[0.1, 0.2]",
        }
        mock_connect.return_value = fake
        b = PGVectorBackend(dsn="postgresql://localhost/x", embedding_dim=3)
        m = b.get(7)
        assert m is not None
        assert m.id == 7
        assert m.content == "parsed content"
        assert m.tags == ["a", "b"]
        assert m.metadata == {"summary": "x"}
        assert m.access_count == 3
        assert m.embedding == [0.1, 0.2]


def test_pgvector_get_none_when_missing():
    with patch("psycopg.connect") as mock_connect:
        from luminary_memory.backends.pgvector import PGVectorBackend

        fake = _FakeConn()
        fake.cur._one = None
        mock_connect.return_value = fake
        b = PGVectorBackend(dsn="postgresql://localhost/x", embedding_dim=3)
        assert b.get(999) is None


def test_pgvector_update_issues_sql():
    with patch("psycopg.connect") as mock_connect:
        from luminary_memory.backends.pgvector import PGVectorBackend

        fake = _FakeConn()
        mock_connect.return_value = fake
        b = PGVectorBackend(dsn="postgresql://localhost/x", embedding_dim=3)
        m = Memory(id=1, content="updated", tags=["x"])
        b.update(m)
        sql = fake.cur.executed[-1][0]
        assert "UPDATE memories" in sql
        assert "WHERE id=%s" in sql


def test_pgvector_delete_cascades_relations():
    with patch("psycopg.connect") as mock_connect:
        from luminary_memory.backends.pgvector import PGVectorBackend

        fake = _FakeConn()
        mock_connect.return_value = fake
        b = PGVectorBackend(dsn="postgresql://localhost/x", embedding_dim=3)
        b.delete(5)
        sqls = [s for s, _ in fake.cur.executed]
        assert any("DELETE FROM relations WHERE memory_id = %s" == s for s in sqls)
        assert any("DELETE FROM memories WHERE id = %s" == s for s in sqls)


def test_pgvector_count():
    with patch("psycopg.connect") as mock_connect:
        from luminary_memory.backends.pgvector import PGVectorBackend

        fake = _FakeConn()
        fake.cur._one = (12,)
        mock_connect.return_value = fake
        b = PGVectorBackend(dsn="postgresql://localhost/x", embedding_dim=3)
        assert b.count() == 12
        assert any("COUNT" in s for s, _ in fake.cur.executed)


def test_pgvector_row_to_memory_tuple():
    from luminary_memory.backends.pgvector import PGVectorBackend

    b = PGVectorBackend.__new__(PGVectorBackend)  # skip __init__ (no conn needed)
    m = b._row_to_memory((
        1, "content here", "{}", None, "[]", 0.5, None,
        "2026-08-17T00:00:00+00:00", "2026-08-17T00:00:00+00:00", None, 0, "[0.5]",
    ))
    assert m.id == 1
    assert m.content == "content here"
    assert m.embedding == [0.5]


def test_pgvector_unit_update_and_delete():
    """update() executes UPDATE and commits; delete() executes DELETE."""
    with patch("psycopg.connect") as mock_connect:
        from luminary_memory.backends.pgvector import PGVectorBackend

        fake = _FakeConn()
        fake.cur._one = None
        mock_connect.return_value = fake
        b = PGVectorBackend(dsn="postgresql://localhost/x", embedding_dim=3)
        committed_before = fake.committed

        m = Memory(id=7, content="updated content", embedding=[0.1, 0.2, 0.3])
        b.update(m)
        assert fake.committed == committed_before + 1
        update_sql = " ".join(fake.cur.executed[-1][0].split())
        assert "UPDATE memories" in update_sql

        b.delete(7)
        assert fake.committed == committed_before + 2
        delete_sql = " ".join(fake.cur.executed[-1][0].split())
        assert "DELETE FROM memories" in delete_sql


def test_pgvector_unit_by_tags_builds_query():
    """by_tags filters with jsonb containment."""
    with patch("psycopg.connect") as mock_connect:
        from luminary_memory.backends.pgvector import PGVectorBackend

        fake = _FakeConn()
        fake.cur._rows = []
        mock_connect.return_value = fake
        b = PGVectorBackend(dsn="postgresql://localhost/x", embedding_dim=3)
        res = b.by_tags(["ci", "alpha"])
        assert res == set()  # by_tags returns a set of ids
        sql = " ".join(fake.cur.executed[-1][0].split())
        assert "SELECT id, tags FROM memories" in sql


def test_pgvector_unit_row_to_memory_json_fallback():
    """Corrupt metadata/tags JSON falls back gracefully (no crash)."""
    with patch("psycopg.connect") as mock_connect:
        from luminary_memory.backends.pgvector import PGVectorBackend

        fake = _FakeConn()
        fake.cur._rows = [
            # id, content, metadata(corrupt), source, tags(corrupt), importance,
            # ttl, created, updated, last_access, access_count, embedding
            (1, "hello", "not-json{", None, "[corrupt", 0.5,
             None, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
             "2026-01-01T00:00:00+00:00", 0, None),
        ]
        mock_connect.return_value = fake
        b = PGVectorBackend(dsn="postgresql://localhost/x", embedding_dim=3)
        res = b.all()
        assert len(res) == 1
        assert res[0].metadata == {}  # fallback, not crash
        assert res[0].tags == []      # fallback, not crash
