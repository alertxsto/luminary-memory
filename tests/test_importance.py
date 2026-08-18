"""Tests for lifecycle/importance.py — auto importance estimation."""
from datetime import UTC, datetime, timedelta

import pytest

from luminary_memory.lifecycle.importance import estimate_importance


def _mem(access=0, last_accessed=None, centrality=0, metadata=None):
    from luminary_memory.types import Memory
    meta = dict(metadata or {})
    if centrality:
        meta["centrality"] = centrality
    return Memory(
        id=1, content="fact", embedding=[0.1] * 384,
        access_count=access, last_accessed_at=last_accessed,
        metadata=meta,
    )


def test_new_memory_low_importance():
    now = datetime.now(UTC)
    m = _mem(access=0, last_accessed=now.isoformat())
    # recency weight contributes 0.3 (fresh), access/centrality 0
    imp = estimate_importance(m, now=now)
    assert imp == pytest.approx(0.3, abs=0.05)


def test_accessed_many_times_high_importance():
    now = datetime.now(UTC)
    m = _mem(access=100, last_accessed=now.isoformat())
    imp = estimate_importance(m, now=now, max_access=100)
    # access_norm 1.0, recency_norm 1.0 → 0.4 + 0.3 = 0.7
    assert imp == pytest.approx(0.7, abs=0.05)


def test_recent_beats_stale():
    now = datetime.now(UTC)
    recent = _mem(access=5, last_accessed=now.isoformat())
    stale = _mem(access=5, last_accessed=(now - timedelta(days=30)).isoformat())
    imp_recent = estimate_importance(recent, now=now, max_access=5)
    imp_stale = estimate_importance(stale, now=now, max_access=5)
    assert imp_recent > imp_stale


def test_centrality_raises_importance():
    now = datetime.now(UTC)
    m_cent = _mem(access=0, last_accessed=(now - timedelta(days=10)).isoformat(), centrality=5)
    m_plain = _mem(access=0, last_accessed=(now - timedelta(days=10)).isoformat())
    imp_cent = estimate_importance(m_cent, now=now, max_centrality=5)
    imp_plain = estimate_importance(m_plain, now=now, max_centrality=5)
    assert imp_cent > imp_plain


def test_clamped_bounds():
    now = datetime.now(UTC)
    m = _mem(access=999999, last_accessed=now.isoformat(), centrality=999)
    imp = estimate_importance(m, now=now, max_access=1, max_centrality=1)
    assert 0.0 <= imp <= 1.0


def test_malformed_timestamp_treated_as_now():
    m = _mem(access=0, last_accessed="garbage-date")
    imp = estimate_importance(m)
    assert 0.0 <= imp <= 1.0


def test_ingest_sets_importance(tmp_path):
    from luminary_memory.api import MemoryClient

    class _E:
        def embed(self, t):
            return [0.1] * 384
        def embed_batch(self, ts):
            return [[0.1] * 384 for _ in ts]

    c = MemoryClient(db_path=str(tmp_path / "i.db"), engine=_E())
    mid = c.ingest("some durable fact")
    m = c.get(mid)
    assert m.importance > 0, "importance should be auto-estimated on ingest"
    c.close()


def test_ingest_importance_disabled(tmp_path):
    from luminary_memory.api import MemoryClient
    from luminary_memory.config import Settings

    class _E:
        def embed(self, t):
            return [0.1] * 384

    # explicit Settings with auto disabled (env-independent)
    c = MemoryClient(db_path=str(tmp_path / "i2.db"), engine=_E(),
                     settings=Settings(importance_auto=False))
    mid = c.ingest("fact")
    m = c.get(mid)
    # default importance 0.5 (types.py) — auto-estimation skipped
    assert float(m.importance) == 0.5, "importance stays at default when auto disabled"
    c.close()


def test_lifecycle_reestimates_importance(tmp_path):
    from datetime import datetime, timedelta

    from luminary_memory.api import MemoryClient

    class _E:
        def embed(self, t):
            return [0.1] * 384

    c = MemoryClient(db_path=str(tmp_path / "l.db"), engine=_E())
    mid = c.ingest("old stale fact")
    # fake last_accessed 30 days ago → importance drops; may be pruned (by design)
    old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    c.backend.conn.execute("UPDATE memories SET last_accessed_at=? WHERE id=?", (old, mid))
    c.backend.conn.commit()
    result = c.run_lifecycle()
    assert result["reestimated"] >= 1
    m = c.get(mid)
    if m is not None:
        assert m.importance < 0.5  # stale memory importance dropped
    c.close()


def test_prune_uses_reestimated_importance(tmp_path):
    from datetime import datetime, timedelta

    from luminary_memory.api import MemoryClient

    class _E:
        def embed(self, t):
            return [0.1] * 384

    c = MemoryClient(db_path=str(tmp_path / "p.db"), engine=_E())
    stale_mid = c.ingest("stale memory to prune")
    c.ingest("fresh memory to keep")
    old = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    c.backend.conn.execute("UPDATE memories SET last_accessed_at=? WHERE id=?", (old, stale_mid))
    c.backend.conn.commit()
    # re-estimate via lifecycle so stale importance drops below threshold
    result = c.run_lifecycle()
    # stale memory should be pruned (importance ~0 < 0.2)
    assert c.get(stale_mid) is None, "stale memory should be pruned after re-estimation"
    assert result["prune"] >= 1
    c.close()
def test_prune_skips_pinned_rules(tmp_path):
    """Pinned rules (importance >= 0.9) survive prune even below threshold."""
    from luminary_memory.api import MemoryClient
    from luminary_memory.lifecycle.prune import prune

    class _E:
        def embed(self, t): return [0.1, 0.1, 0.1]
        def embed_batch(self, ts): return [[0.1, 0.1, 0.1] for _ in ts]

    c = MemoryClient(db_path=str(tmp_path / "p.db"), engine=_E())
    c.ingest("rule: jangan pakai em dash", tags=["rule"])  # importance 0.3 auto
    m = c.get(c.recall("em dash", limit=1).memories[0].id)
    m.importance = 0.95  # pin it
    c.update(m)
    c.ingest("trash worklog", tags=["trash"])  # low importance

    _removed = prune(c.backend, min_importance=0.5)
    mems = c.list(limit=0)
    contents = [x.content for x in mems]
    assert any("em dash" in c for c in contents), "pinned rule must survive"
    assert not any("trash" in c for c in contents), "low-value must be pruned"
def test_rule_auto_replace_replaces_similar(tmp_path):
    """Ingesting a similar rule replaces the old one (no contradiction)."""
    from luminary_memory.api import MemoryClient

    class _E:
        def embed(self, t): return [float(len(t)), 0.0, 0.0]
        def embed_batch(self, ts): return [[float(len(t)), 0.0, 0.0] for t in ts]

    c = MemoryClient(db_path=str(tmp_path / "r.db"), engine=_E())
    first = c.ingest("JANGAN pakai tabel di telegram", tags=["rule"])
    assert first is not None
    mems_before = c.list(limit=0)
    assert len(mems_before) == 1
    assert mems_before[0].content == "JANGAN pakai tabel di telegram"
    # Second ingest is similar (collinear embedding) -> should replace in place
    second = c.ingest("WAJIB pakai markdown table di telegram", tags=["rule"])
    mems = c.list(limit=0)
    assert second == first, "auto-replace must return the original id"
    assert len(mems) == 1, "store should still have exactly one entry after replace"
    assert mems[0].content == "WAJIB pakai markdown table di telegram"
    c.close()


def test_lifecycle_preserves_pinned_rule_importance(tmp_path):
    """run_lifecycle() must not downgrade pinned rule importance back to recency/access level."""
    from luminary_memory.api import MemoryClient

    class _E:
        def embed(self, t): return [0.1] * 384
        def embed_batch(self, ts): return [[0.1] * 384 for _ in ts]

    c = MemoryClient(db_path=str(tmp_path / "pinned.db"), engine=_E())
    mid = c.ingest("rule: always use markdown tables", tags=["rule"])
    m = c.get(mid)
    m.importance = 0.95  # pinned rule
    c.update(m)

    # Run lifecycle re-estimation pass
    res = c.run_lifecycle()
    assert res["reestimated"] == 0, "pinned rules must be skipped during re-estimation"
    m_after = c.get(mid)
    assert m_after is not None
    assert m_after.importance == 0.95, "pinned rule importance must not be downgraded by lifecycle"
    c.close()

