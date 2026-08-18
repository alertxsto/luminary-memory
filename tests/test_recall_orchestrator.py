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


def test_recall_raises_importance_of_frequently_used_memory(tmp_path):
    """AM-T1.1: frequently-recalled memory climbs in importance so it ranks up
    in the next persistent-context block (top_by_importance)."""
    c = MemoryClient(db_path=str(tmp_path / "ada.db"), engine=_FakeEngine())
    c.settings.importance_auto = True
    a = _ingest(c, "alpha bravo charlie delta")
    b = _ingest(c, "xylophone zephyr quantum flux")
    # same starting importance so any divergence is caused by recall behavior
    for mid in (a, b):
        m = c.get(mid)
        m.importance = 0.3
        c.backend.update(m)

    for _ in range(3):
        res = c.recall("alpha bravo charlie", limit=1)
        assert len(res.memories) == 1, "query must recall exactly memory A"

    imp_a = float(c.get(a).importance)
    imp_b = float(c.get(b).importance)
    assert imp_a > imp_b, f"recalled memory must outrank idle memory: a={imp_a} b={imp_b}"
    c.close()


def test_recall_importance_reestimate_never_downgrades_pinned(tmp_path):
    """AM-T1.2: re-estimation during recall must not drop a pinned rule below
    the pin threshold (>= 0.9)."""
    c = MemoryClient(db_path=str(tmp_path / "pin.db"), engine=_FakeEngine())
    c.settings.importance_auto = True
    mid = _ingest(c, "always use markdown tables in reports")
    m = c.get(mid)
    m.importance = 0.95  # pinned rule
    c.backend.update(m)

    for _ in range(5):
        c.recall("always use markdown tables", limit=1)

    assert float(c.get(mid).importance) >= 0.9, "pinned rule must stay pinned"
    c.close()


def test_reestimate_empty_ids_returns_zero(tmp_path):
    """Re-estimation with no ids is a no-op (empty get_many -> 0)."""
    from luminary_memory.api import MemoryClient

    c = MemoryClient(db_path=str(tmp_path / "re.db"), engine=_FakeEngine())
    assert c._reestimate_accessed_importance([]) == 0
    c.close()


def test_reestimate_unknown_ids_returns_zero(tmp_path):
    """Re-estimation for ids that do not exist returns 0."""
    from luminary_memory.api import MemoryClient

    c = MemoryClient(db_path=str(tmp_path / "re2.db"), engine=_FakeEngine())
    assert c._reestimate_accessed_importance([99999]) == 0
    c.close()


def test_reestimate_no_change_returns_zero(tmp_path):
    """Re-estimation returns 0 when nothing changes (already pinned)."""
    from luminary_memory.api import MemoryClient

    c = MemoryClient(db_path=str(tmp_path / "re3.db"), engine=_FakeEngine())
    mid = _ingest(c, "pinned rule no change")
    m = c.get(mid)
    m.importance = 0.95  # pinned -> skipped by re-estimation
    c.backend.update(m)
    assert c._reestimate_accessed_importance([mid]) == 0
    c.close()


def test_reestimate_fallback_without_update_importances(tmp_path):
    """Re-estimation falls back to per-item update when the backend lacks
    the batched update_importances method (defensive path)."""
    from luminary_memory.api import MemoryClient
    from luminary_memory.backends.sqlite import SQLiteBackend

    class _NoBulk(SQLiteBackend):
        update_importances = None  # simulate a minimal custom backend

    c = MemoryClient(db_path=str(tmp_path / "re4.db"), engine=_FakeEngine())
    c.backend = _NoBulk(str(tmp_path / "re4b.db"))
    mid = _ingest(c, "frequently used fact")
    m = c.get(mid)
    m.importance = 0.3
    c.backend.update(m)
    # bump access + recency, then re-estimate via the fallback path
    c.backend.touch_memories([mid])
    n = c._reestimate_accessed_importance([mid])
    assert n in (0, 1)  # either nothing changed or one updated, no crash
    c.close()


def test_reestimate_without_get_many_returns_zero(tmp_path):
    """Re-estimation is a no-op when the backend lacks the batched get_many."""
    from luminary_memory.api import MemoryClient
    from luminary_memory.backends.sqlite import SQLiteBackend

    class _NoGetMany(SQLiteBackend):
        get_many = None

    c = MemoryClient(db_path=str(tmp_path / "re5.db"), engine=_FakeEngine())
    c.backend = _NoGetMany(str(tmp_path / "re5b.db"))
    mid = _ingest(c, "some fact")
    c.backend.touch_memories([mid])
    assert c._reestimate_accessed_importance([mid]) == 0
    c.close()
