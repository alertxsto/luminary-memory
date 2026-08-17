from datetime import UTC, datetime, timedelta

from luminary_memory.backends.sqlite import SQLiteBackend
from luminary_memory.lifecycle.cleanup import cleanup_expired
from luminary_memory.lifecycle.consolidate import consolidate
from luminary_memory.lifecycle.prune import prune
from luminary_memory.types import Memory


def test_cleanup_removes_expired_and_keeps_valid(tmp_path):
    b = SQLiteBackend(str(tmp_path / "t.db"))
    expired = Memory(content="stale fact", ttl_seconds=10,
                     created_at=(datetime.now(UTC) - timedelta(hours=5)).isoformat())
    valid = Memory(content="fresh fact", ttl_seconds=3600,
                   created_at=datetime.now(UTC).isoformat())
    no_ttl = Memory(content="永恒 memory")
    b.add(expired)
    b.add(valid)
    b.add(no_ttl)
    removed = cleanup_expired(b)
    assert removed == 1
    assert b.count() == 2
    assert all(m.content != "stale fact" for m in b.all())


def test_cleanup_handles_no_expired(tmp_path):
    b = SQLiteBackend(str(tmp_path / "t.db"))
    b.add(Memory(content="persistent", ttl_seconds=3600))
    assert cleanup_expired(b) == 0
    assert b.count() == 1


def test_consolidate_merges_near_duplicates(tmp_path):
    b = SQLiteBackend(str(tmp_path / "t.db"))
    base = "postgres vector similarity search with pgvector is fast"
    m1 = Memory(content=base, tags=["database"], access_count=3)
    m2 = Memory(content=base, tags=["vector"], access_count=5)
    b.add(m1); b.add(m2)
    merged = consolidate(b, threshold=0.9)
    assert merged == 1
    assert b.count() == 1
    survivor = b.all()[0]
    assert survivor.access_count == 8
    assert set(survivor.tags) == {"database", "vector"}


def test_consolidate_keeps_distinct_memories(tmp_path):
    b = SQLiteBackend(str(tmp_path / "t.db"))
    b.add(Memory(content="postgres vector search very fast efficient"))
    b.add(Memory(content="cooking pasta with tomato sauce and basil"))
    merged = consolidate(b, threshold=0.9)
    assert merged == 0
    assert b.count() == 2


def test_prune_removes_low_importance_below_threshold(tmp_path):
    b = SQLiteBackend(str(tmp_path / "t.db"))
    b.add(Memory(content="forgettable note", importance=0.1, access_count=0))
    b.add(Memory(content="important decision", importance=0.9, access_count=0))
    b.add(Memory(content="another trivial fact", importance=0.05, access_count=0))
    removed = prune(b, min_importance=0.2)
    assert removed == 2
    assert b.count() == 1
    assert b.all()[0].content == "important decision"


def test_prune_respects_max_count_ceiling(tmp_path):
    b = SQLiteBackend(str(tmp_path / "t.db"))
    for i in range(5):
        b.add(Memory(content=f"note {i} with distinct suffix {i}", importance=0.5))
    removed = prune(b, min_importance=0.0, max_count=3)
    assert b.count() == 3
    assert removed == 2


def test_runner_cleanup_consolidate_prune_orchestrator(tmp_path):
    from luminary_memory.api import MemoryClient

    class FakeE:
        def embed(self, t): return [0.1] * 384

    c = MemoryClient(db_path=str(tmp_path / "t.db"), engine=FakeE())
    from luminary_memory.types import Memory as MType
    expired = MType(content="expired soon", ttl_seconds=5,
                    created_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                    embedding=[0.1] * 384)
    c.backend.add(expired)
    before = c.count()
    result = c.run_lifecycle()
    assert isinstance(result, dict)
    assert "cleanup" in result and "consolidate" in result and "prune" in result
    assert c.count() <= before
