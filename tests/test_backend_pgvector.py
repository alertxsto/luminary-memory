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
    pass


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
