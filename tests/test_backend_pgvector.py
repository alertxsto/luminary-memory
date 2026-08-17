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
