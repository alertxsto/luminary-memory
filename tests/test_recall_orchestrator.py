from luminary_memory.api import MemoryClient
from luminary_memory.types import RecallResult


class _FakeEngine:
    def embed(self, text: str) -> list[float]:
        # simple hash-embedding so distinct texts produce distinguishable vectors
        v = [0.0] * 384
        v[hash(text) % 384] = 1.0
        return v


def _ingest(c, content, tags=None):
    mid = c.ingest(content, tags=tags or [])
    assert mid is not None
    return mid


def test_ingest_then_recall_returns_recall_result(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), engine=_FakeEngine())
    _ingest(c, "postgres vector search indexing is fast", tags=["database"])
    _ingest(c, "cooking pasta with tomato sauce", tags=["cooking"])
    res = c.recall("postgres vector index", limit=5)
    assert isinstance(res, RecallResult)
    assert len(res.memories) > 0
    assert res.memories[0].content.startswith("postgres")
    assert res.strategies_hit
    assert res.scores


def test_recall_respects_token_budget(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), engine=_FakeEngine())
    for w in ["word repeat", "word repeat duplicate", "postgres vector index"]:
        _ingest(c, w)
    res = c.recall("word", limit=10, token_budget=2)
    total_tokens = sum(len(m.content.split()) for m in res.memories)
    assert total_tokens <= 2


def test_recall_dedup_collapses_near_duplicates(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), engine=_FakeEngine())
    _ingest(c, "alpha beta gamma delta")
    _ingest(c, "alpha beta gamma delta")
    res = c.recall("alpha beta gamma", limit=5)
    contents = [m.content for m in res.memories]
    assert contents.count("alpha beta gamma delta") == 1


def test_recall_propagates_empty_store(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), engine=_FakeEngine())
    res = c.recall("anything", limit=5)
    assert res.memories == []


def test_recall_access_count_bumps(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), engine=_FakeEngine())
    mid = _ingest(c, "postgres vector index")
    c.recall("postgres")
    c.recall("postgres")
    m = c.get(mid)
    assert m.access_count >= 1


def test_recall_fallback_empty_store(tmp_path):
    """Empty store: recall returns empty result."""
    c = MemoryClient(db_path=str(tmp_path / "e.db"), engine=_FakeEngine())
    res = c.recall("anything", limit=5)
    assert res.memories == []
    assert res.scores == []


def test_recall_surfaces_important_rules_in_mixed_store(tmp_path):
    """Important rules surface even in a store with recent noise."""
    c = MemoryClient(db_path=str(tmp_path / "mixed.db"), engine=_FakeEngine())
    rule = _ingest(c, "always deploy to staging before production", tags=["rule"])
    noise = _ingest(c, "had coffee this morning")
    for _ in range(5):
        _ingest(c, "random conversation filler phrase")

    ms = [c.get(rule), c.get(noise)]
    ms[0].importance = 0.95
    ms[1].importance = 0.05
    c.backend.update(ms[0])
    c.backend.update(ms[1])

    res = c.recall("deploy to staging", limit=10)
    assert len(res.memories) >= 1
    contents = [m.content for m in res.memories]
    assert any("staging" in c for c in contents), "important rule must surface"
    assert res.strategies_hit


def test_recall_temporal_surfaces_recent_without_matches(tmp_path):
    """When no semantic/keyword match, temporal still provides recent context."""
    c = MemoryClient(db_path=str(tmp_path / "temporal.db"), engine=_FakeEngine())
    rule = _ingest(c, "always use tabs not spaces in this project", tags=["rule"])
    r = c.get(rule)
    r.importance = 0.95
    c.backend.update(r)

    res = c.recall("zzxywq completely unrelated gibberish", limit=5)
    assert len(res.memories) >= 1
    assert "temporal" in (res.strategies_hit or {}), "temporal provides fallback context"
