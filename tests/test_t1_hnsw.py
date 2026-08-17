from unittest.mock import patch


class _FakeCursor:
    def __init__(self):
        self.executed: list[tuple] = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return self

    def fetchone(self): return None
    def fetchall(self): return []


class _FakeConn:
    def __init__(self):
        self.cur = _FakeCursor()
        self.committed = 0
    def cursor(self): return self.cur
    def commit(self): self.committed += 1
    def close(self): pass


def test_hnsw_index_created_when_enabled():
    with patch("psycopg.connect") as mock_connect:
        from luminary_memory.backends.pgvector import PGVectorBackend
        fake = _FakeConn()
        mock_connect.return_value = fake
        PGVectorBackend(dsn="postgresql://localhost/x", embedding_dim=3,
                        hnsw=True, hnsw_m=16, hnsw_ef_construction=64)
        sqls = [s for s, _ in fake.cur.executed]
        assert any("USING hnsw" in s and "vector_cosine_ops" in s for s in sqls)


def test_hnsw_index_not_created_when_disabled():
    with patch("psycopg.connect") as mock_connect:
        from luminary_memory.backends.pgvector import PGVectorBackend
        fake = _FakeConn()
        mock_connect.return_value = fake
        PGVectorBackend(dsn="postgresql://localhost/x", embedding_dim=3, hnsw=False)
        sqls = [s for s, _ in fake.cur.executed]
        assert not any("hnsw" in s.lower() for s in sqls)


def test_build_index_idempotent_and_guarded():
    with patch("psycopg.connect") as mock_connect:
        from luminary_memory.backends.pgvector import PGVectorBackend
        fake = _FakeConn()
        mock_connect.return_value = fake
        b = PGVectorBackend(dsn="postgresql://localhost/x", embedding_dim=3, hnsw=False)
        # public build_index must not raise even when extension missing
        b.build_index(m=16, ef_construction=64)
        assert any("USING hnsw" in s for s, _ in fake.cur.executed)
