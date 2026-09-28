"""Retrieval correctness and bounded database scan regressions."""

from datetime import UTC, datetime, timedelta

import numpy as np

from luminary_memory.backends.sqlite import SQLiteBackend
from luminary_memory.recall.temporal import temporal_recall
from luminary_memory.types import Memory


class _BoundedCursor:
    def __init__(self, cursor, max_batch):
        self.cursor = cursor
        self.max_batch = max_batch

    def fetchall(self):
        raise AssertionError("candidate scan must not materialize all rows")

    def fetchmany(self, size=None):
        assert size is not None and 0 < size <= self.max_batch
        return self.cursor.fetchmany(size)

    def __iter__(self):
        # Iteration via a sqlite cursor is streaming and does not call fetchall.
        return iter(self.cursor)


class _ObserveConnection:
    def __init__(self, connection, observed):
        self.connection = connection
        self.observed = observed

    def execute(self, query, params=()):
        cursor = self.connection.execute(query, params)
        if query.startswith((
            "SELECT m.id, m.embedding FROM memories m",
            "SELECT m.id, COALESCE(m.observed_at, m.created_at) AS temporal_at",
        )):
            self.observed.append(query)
            return _BoundedCursor(cursor, 256)
        return cursor

    def __getattr__(self, name):
        return getattr(self.connection, name)


def test_vector_search_streams_candidates_and_fetches_winners(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "vector.db"))
    rows = [
        Memory(content=f"item {i}", embedding=[0.0, 1.0], user_id="alice")
        for i in range(600)
    ]
    backend.add_many(rows)
    backend.add(Memory(content="global best", embedding=[1.0, 0.0]))
    winner = backend.add(Memory(content="best", embedding=[1.0, 0.0], user_id="alice"))
    backend.add(Memory(
        content="expired", embedding=[1.0, 0.0], user_id="alice",
        valid_to="2020-01-01T00:00:00+00:00",
    ))
    backend.add(Memory(content="wrong dimension", embedding=[1.0], user_id="alice"))
    backend.conn.execute(
        "INSERT INTO memories (content, embedding, user_id) VALUES (?, ?, ?)",
        ("corrupt", b"x", "alice"),
    )
    backend.conn.execute(
        "INSERT INTO memories (content, embedding, user_id) VALUES (?, ?, ?)",
        ("nonfinite", np.array([np.nan, 0.0], dtype=np.float32).tobytes(), "alice"),
    )
    backend.conn.commit()
    seen = []
    backend._local.conn = _ObserveConnection(backend.conn, seen)

    result = backend.vector_search(
        [1.0, 0.0], limit=1, scope={"user_id": "alice"}, include_global=False,
    )
    assert [memory.id for memory, _ in result] == [winner]
    assert len(seen) == 1
    backend.close()


def test_vector_search_ties_limits_and_invalid_queries(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "vectors.db"))
    ids = backend.add_many([
        Memory(content=f"equal {i}", embedding=[1.0, 0.0]) for i in range(1005)
    ])
    assert [memory.id for memory, _ in backend.vector_search([1.0, 0.0], limit=2)] == ids[:2]
    assert [memory.id for memory, _ in backend.vector_search([1.0, 0.0], limit=None)] == ids
    assert [memory.id for memory, _ in backend.vector_search([1.0, 0.0], limit=-1)] == ids
    assert backend.vector_search([1.0, 0.0], limit=0) == []
    assert backend.vector_search([float("nan"), 0.0], limit=1) == []
    assert backend.vector_search([float("inf"), 0.0], limit=1) == []
    backend.close()


def test_temporal_recall_streams_lightweight_rows_and_keeps_scoped_best(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "temporal.db"))
    past = (datetime.now(UTC) - timedelta(days=365)).isoformat()
    backend.add_many([
        Memory(content=f"old {i}", user_id="alice", created_at=past)
        for i in range(600)
    ])
    backend.add(Memory(
        content="global newest", observed_at=datetime.now(UTC).isoformat(), access_count=100,
    ))
    winner = backend.add(Memory(
        content="scoped winner", user_id="alice", created_at=datetime.now(UTC).isoformat(),
    ))
    backend.add(Memory(
        content="expired best", user_id="alice", observed_at=datetime.now(UTC).isoformat(),
        access_count=100, valid_to=past,
    ))
    seen = []
    backend._local.conn = _ObserveConnection(backend.conn, seen)

    result = temporal_recall(
        backend, limit=1, scope={"user_id": "alice"}, include_global=False,
    )
    assert [memory.id for memory, _, _ in result] == [winner]
    assert len(seen) == 1
    backend.close()

def test_empty_scoped_temporal_scan_never_hydrates_full_store(tmp_path):
    class NoFullStore(SQLiteBackend):
        def all(self):
            raise AssertionError("empty scoped scan must not hydrate the entire store")

    backend = NoFullStore(str(tmp_path / "empty-scope.db"))
    backend.add(Memory(content="another user's fact", user_id="bob"))
    assert temporal_recall(
        backend, limit=1, scope={"user_id": "alice"}, include_global=False,
    ) == []
    backend.close()


def test_temporal_recall_ties_and_unlimited(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "ties.db"))
    timestamp = datetime.now(UTC).isoformat()
    ids = backend.add_many([
        Memory(content=f"tie {i}", created_at=timestamp) for i in range(1005)
    ])
    assert [memory.id for memory, _, _ in temporal_recall(backend, limit=2)] == ids[:2]
    assert [memory.id for memory, _, _ in temporal_recall(backend, limit=None)] == ids
    assert temporal_recall(backend, limit=0) == []
    backend.close()
