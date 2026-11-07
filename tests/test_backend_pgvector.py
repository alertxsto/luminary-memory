import os
import uuid

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




def test_backend_factory_returns_sqlite_by_default():
    from luminary_memory.backends import get_backend
    from luminary_memory.config import Settings

    b = get_backend(Settings(backend="sqlite", db_path=":memory:"))
    assert b.__class__.__name__ == "SQLiteBackend"
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



@pytest.fixture
def real_pg_backend():
    if not _pg_available():
        pytest.skip(_SKIP_MSG)
    import psycopg
    from psycopg.conninfo import make_conninfo

    from luminary_memory.backends.pgvector import PGVectorBackend
    dsn = os.environ.get("LUMINARY_PG_DSN", os.environ.get("PG_DSN", ""))
    admin = psycopg.connect(dsn, autocommit=True)
    schema = "backend_test_" + uuid.uuid4().hex
    admin.execute(f'CREATE SCHEMA "{schema}"')
    backend = PGVectorBackend(dsn=make_conninfo(dsn, options=f"-c search_path={schema},public"), embedding_dim=3)
    try:
        yield backend
    finally:
        backend.close()
        admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        admin.close()


def test_pgvector_real_round_trip_and_missing_row(real_pg_backend):
    backend = real_pg_backend
    memory_id = backend.add(Memory(content="parsed content", metadata={"summary": "x"}, tags=["a", "b"],
                                   embedding=[0.1, 0.2, 0.3], access_count=3))
    memory = backend.get(memory_id)
    assert memory.content == "parsed content" and memory.metadata == {"summary": "x"}
    assert memory.tags == ["a", "b"] and memory.access_count == 3
    assert memory.embedding == pytest.approx([0.1, 0.2, 0.3])
    assert backend.get(memory_id + 10000) is None
    assert backend.count() == 1


def test_pgvector_real_scoped_keyword_vector_and_tags(real_pg_backend):
    backend = real_pg_backend
    own = backend.add(Memory(content="hello deployment world", tags=["ci", "alpha"],
                            embedding=[1.0, 0.0, 0.0], user_id="alice", workspace_id="w", agent_id="pi"))
    backend.add(Memory(content="hello foreign world", tags=["ci", "beta"],
                       embedding=[1.0, 0.0, 0.0], user_id="bob", workspace_id="w", agent_id="pi"))
    scope = {"user_id": "alice", "workspace_id": "w", "agent_id": "pi"}
    assert [memory.id for memory, _ in backend.keyword_search("hello", limit=5, scope=scope, include_global=False)] == [own]
    assert [memory.id for memory, _ in backend.vector_search([1.0, 0.0, 0.0], limit=5, scope=scope, include_global=False)] == [own]
    assert backend.by_tags(["alpha"]) == {own}
    assert backend.by_tags(["absent"]) == set()


def test_pgvector_real_update_and_graph_cascade(real_pg_backend):
    from luminary_memory.recall.graph import index_memory_entities
    backend = real_pg_backend
    memory = Memory(content="alpha deployment service", tags=["alpha"], embedding=[1.0, 0.0, 0.0])
    memory.id = backend.add(memory)
    index_memory_entities(backend, memory)
    assert backend.conn.execute("SELECT COUNT(*) FROM relations WHERE memory_id=%s", (memory.id,)).fetchone()[0] > 0
    memory.content = "updated deployment"
    backend.update(memory)
    assert backend.get(memory.id).content == "updated deployment"
    assert backend.get(memory.id).revision == 2
    backend.delete(memory.id)
    assert backend.get(memory.id) is None and backend.count() == 0
    assert backend.conn.execute("SELECT COUNT(*) FROM relations WHERE memory_id=%s", (memory.id,)).fetchone()[0] == 0


def test_pgvector_real_non_unique_insert_error_is_not_duplicate(real_pg_backend):
    from psycopg.errors import NotNullViolation
    backend = real_pg_backend
    backend.add(Memory(content="existing fact"))
    with pytest.raises(NotNullViolation):
        backend.add(Memory(content=None))
    assert backend.count() == 1


def test_pgvector_row_parser_rejects_corrupt_containers():
    from luminary_memory.backends.pgvector import PGVectorBackend
    backend = PGVectorBackend.__new__(PGVectorBackend)
    memory = backend._row_to_memory({"id": 1, "content": "hello", "metadata": "not-json{", "tags": "[corrupt"})
    assert memory.metadata == {} and memory.tags == []
