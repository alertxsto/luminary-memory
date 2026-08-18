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


def _sem_backend(tmp_path, memories, name="sem.db"):
    """Real SQLiteBackend seeded with memories that carry explicit embeddings.

    Using the actual backend (not an in-memory stub) proves the embeddings
    survive the float32 blob round-trip through SQLite and that consolidate
    reads them back correctly for semantic merging.
    """
    b = SQLiteBackend(str(tmp_path / name))
    for m in memories:
        b.add(m)
    return b


def test_consolidate_semantic_merges_same_meaning_different_words(tmp_path):
    """Embedding-cosine merges paraphrases that Jaccard would miss."""
    from luminary_memory.types import Memory
    # two vectors that are near-identical (cosine ~1.0) but texts share no tokens
    v = [1.0, 0.5, 0.25]
    m1 = Memory(content="deploy target is the staging cluster", embedding=v, access_count=0, tags=[])
    m2 = Memory(content="we ship to the production cluster now",
                embedding=[0.98, 0.5, 0.25], access_count=0, tags=[])
    b = _sem_backend(tmp_path, [m1, m2])
    merged = consolidate(b, semantic=True, semantic_threshold=0.9)
    assert merged == 1
    assert b.count() == 1


def test_consolidate_semantic_falls_back_to_jaccard_without_embeddings(tmp_path):
    """Memories without embeddings fall back to Jaccard token overlap."""
    from luminary_memory.types import Memory
    m1 = Memory(content="postgres index tuning guide", embedding=None, access_count=0, tags=[])
    m2 = Memory(content="postgres index tuning guide for latency", embedding=None, access_count=0, tags=[])
    b = _sem_backend(tmp_path, [m1, m2])
    merged = consolidate(b, semantic=True, threshold=0.6)
    assert merged == 1  # Jaccard fallback merged them


def test_consolidate_semantic_keeps_unrelated(tmp_path):
    from luminary_memory.types import Memory
    m1 = Memory(content="deploy to staging", embedding=[1.0, 0.0], access_count=0, tags=[])
    m2 = Memory(content="user prefers dark mode", embedding=[0.0, 1.0], access_count=0, tags=[])
    b = _sem_backend(tmp_path, [m1, m2])
    merged = consolidate(b, semantic=True, semantic_threshold=0.9)
    assert merged == 0
    assert b.count() == 2


def test_consolidate_jaccard_only_when_semantic_false(tmp_path):
    """semantic=False keeps legacy Jaccard-only behavior."""
    from luminary_memory.types import Memory
    build = lambda: (Memory(content="alpha beta gamma delta", embedding=[1.0, 0.5],
                            access_count=0, tags=[]),
                     Memory(content="alpha beta gamma delta epsilon", embedding=[0.99, 0.5],
                            access_count=0, tags=[]))
    a1, a2 = build()
    b = _sem_backend(tmp_path, [a1, a2], "a.db")
    # Jaccard = 4/5 = 0.8 → threshold 0.7 merges, threshold 0.9 doesn't
    assert consolidate(b, semantic=False, threshold=0.7) == 1
    b1, b2 = build()
    b3 = _sem_backend(tmp_path, [b1, b2], "b.db")
    assert consolidate(b3, semantic=False, threshold=0.9) == 0


def test_runner_env_semantic_false(monkeypatch, tmp_path):
    """LUMINARY_CONSOLIDATE_SEMANTIC=false disables semantic consolidation."""
    from luminary_memory.config import Settings
    monkeypatch.setenv("LUMINARY_CONSOLIDATE_SEMANTIC", "false")
    s = Settings()
    assert s.consolidate_semantic is False


def test_runner_env_semantic_default_true():
    from luminary_memory.config import Settings
    s = Settings()
    assert s.consolidate_semantic is True


def test_consolidate_degenerate_embedding_falls_back_jaccard(tmp_path):
    """All-equal embeddings carry no signal — must NOT merge unrelated text."""
    from luminary_memory.types import Memory
    v = [0.5] * 384  # degenerate: identical constant vector
    m1 = Memory(content="deploy target is the staging cluster", embedding=v, access_count=0, tags=[])
    m2 = Memory(content="user prefers dark mode", embedding=v, access_count=0, tags=[])
    b = _sem_backend(tmp_path, [m1, m2])
    merged = consolidate(b, semantic=True, semantic_threshold=0.85)
    assert merged == 0, "degenerate embeddings must not merge unrelated memories"
    assert b.count() == 2


def test_run_lifecycle_applies_max_memories_cap(tmp_path):
    """run_lifecycle must enforce the max_memories cap (regression: the cap
    was never passed to prune, so oversized stores never shrank)."""
    from luminary_memory.api import MemoryClient

    class _E:
        def embed(self, t): return [0.1, 0.1, 0.1]
        def embed_batch(self, ts): return [[0.1, 0.1, 0.1] for _ in ts]

    c = MemoryClient(db_path=str(tmp_path / "cap.db"), engine=_E())
    c.settings.max_memories = 5
    for i in range(10):
        c.ingest(f"fact number {i}", tags=["t"], source="test")
    assert c.count() == 10

    res = c.run_lifecycle()
    assert res.get("prune", 0) >= 5, f"expected prune to enforce cap, got {res}"
    assert c.count() <= 5, f"store must shrink to <=5, got {c.count()}"
    c.close()


def test_max_memories_env_var_maps_to_settings(monkeypatch):
    from luminary_memory.config import Settings
    monkeypatch.setenv("LUMINARY_MAX_MEMORIES", "250")
    assert Settings().max_memories == 250
