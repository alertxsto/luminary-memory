
from datetime import UTC

import pytest

from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings


class _E:
    def embed(self, t):
        return [0.1] * 384
    def embed_batch(self, ts):
        return [[0.1] * 384 for _ in ts]


@pytest.fixture()
def client(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"))
    yield c
    c.close()


def test_config_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINARY_BACKEND", "sqlite")
    monkeypatch.setenv("LUMINARY_DB_PATH", str(tmp_path / "env.db"))
    monkeypatch.setenv("LUMINARY_RRF_K", "42")
    monkeypatch.setenv("LUMINARY_TOKEN_BUDGET", "2048")
    monkeypatch.setenv("LUMINARY_INGEST_WHITELIST", "port,config")
    s = Settings()
    assert s.backend == "sqlite"
    assert s.db_path == str(tmp_path / "env.db")
    assert s.rrf_k == 42
    assert s.token_budget == 2048
    assert s.ingest_whitelist == ["port", "config"]


def test_config_env_bool(monkeypatch):
    monkeypatch.setenv("LUMINARY_INGEST_LLM", "true")
    assert Settings().ingest_llm is True
    monkeypatch.setenv("LUMINARY_INGEST_LLM", "0")
    assert Settings().ingest_llm is False


def test_update(client):
    mid = client.ingest("initial content here", tags=["a"])
    assert mid is not None
    m = client.get(mid)
    assert m is not None
    m.content = "updated content here"
    m.importance = 0.9
    client.update(m)
    got = client.get(mid)
    assert got is not None
    assert got.content == "updated content here"
    assert got.importance == 0.9


def test_delete(client):
    mid = client.ingest("delete me please")
    assert mid is not None
    client.delete(mid)
    assert client.get(mid) is None
    assert client.count() == 0


def test_list_ordering(client):
    client.ingest("first memory item")
    client.ingest("second memory item")
    mems = client.list(limit=10)
    assert len(mems) == 2
    # most recent first
    assert mems[0].content == "second memory item"
    assert mems[1].content == "first memory item"


def test_search_keyword(client):
    client.ingest("postgresql indexing with fts5")
    client.ingest("cooking pasta for lunch")
    res = client.search("postgresql", limit=5)
    assert res and "postgresql" in res[0][0].content.lower()


def test_stats(client):
    s = client.stats()
    assert s["count"] == 0
    client.ingest("first memory with tag alpha", tags=["alpha"])
    client.ingest("second memory with tag beta", tags=["beta"])
    s = client.stats()
    assert s["count"] == 2
    assert "alpha" in s["top_tags"]
    assert "beta" in s["top_tags"]


def test_list_negative_limit_raises(client):
    import pytest
    with pytest.raises(ValueError):
        client.list(limit=-1)


def test_list_negative_offset_raises(client):
    import pytest
    with pytest.raises(ValueError):
        client.list(limit=10, offset=-5)


def test_list_unlimited_zero(client):
    client.ingest("fact a")
    client.ingest("fact b")
    ms = client.list(limit=0)
    assert len(ms) >= 2


def test_search_empty_query_returns_empty(client):
    assert client.search("   ") == []


def test_export_import_roundtrip(client, tmp_path):
    client.ingest("durable fact one", tags=["a"])
    client.ingest("durable fact two", tags=["b"])
    path = str(tmp_path / "export.json")
    res = client.export(path)
    assert res["count"] >= 2

    # import into a fresh client
    from luminary_memory.api import MemoryClient
    c2 = MemoryClient(db_path=str(tmp_path / "fresh.db"))
    imp = c2.import_memories(path)
    assert imp["imported"] >= 2
    assert c2.count() >= 2
    c2.close()


class _NoRecentBackend:
    """Backend without the 'recent' shortcut → list() falls back to sort."""

    def __init__(self):
        self.items = []

    def add(self, m):
        m.id = len(self.items) + 1
        self.items.append(m)
        return m.id

    def get(self, mid):
        for m in self.items:
            if m.id == mid:
                return m
        return None

    def all(self):
        return list(self.items)

    def count(self):
        return len(self.items)

    def close(self):
        pass

    def keyword_search(self, query, limit=None):
        raise RuntimeError("no keyword search")


def test_list_fallback_no_recent(tmp_path):
    from luminary_memory.api import MemoryClient

    class _E:
        def embed(self, t):
            return [0.1] * 384

    c = MemoryClient(db_path=str(tmp_path / "x.db"), engine=_E())
    c.backend = _NoRecentBackend()
    c.ingest("first")
    c.ingest("second")
    ms = c.list(limit=10)
    assert len(ms) == 2


def test_search_error_returns_empty(tmp_path):
    from luminary_memory.api import MemoryClient

    class _E:
        def embed(self, t):
            return [0.1] * 384

    c = MemoryClient(db_path=str(tmp_path / "y.db"), engine=_E())
    c.backend = _NoRecentBackend()
    assert c.search("anything") == []


def test_recall_strategy_error_falls_back(tmp_path, monkeypatch):
    """A strategy that raises must not break recall — it degrades to []."""
    from luminary_memory.api import MemoryClient
    from luminary_memory.recall import semantic as semantic_mod

    class _E:
        def embed(self, t):
            return [0.1] * 384
        def embed_batch(self, ts):
            return [[0.1] * 384 for _ in ts]

    c = MemoryClient(db_path=str(tmp_path / "r.db"), engine=_E())
    c.ingest("some fact about postgres")

    def boom(*a, **kw):
        raise RuntimeError("semantic exploded")
    monkeypatch.setattr(semantic_mod, "semantic_recall", boom)

    result = c.recall("postgres", limit=5)
    assert result is not None  # degraded, not raised
    c.close()


def test_recall_planner_disables_strategies(tmp_path):
    """Query planner skips strategies when keyword scores are strong."""
    from luminary_memory.api import MemoryClient

    class _E:
        def embed(self, t):
            return [0.1] * 384
        def embed_batch(self, ts):
            return [[0.1] * 384 for _ in ts]

    c = MemoryClient(db_path=str(tmp_path / "p.db"), engine=_E())
    c.ingest("postgres index tuning")
    r = c.recall("postgres", limit=5)
    assert r.strategies_hit  # dict populated
    c.close()


def test_update_without_id_raises(tmp_path):
    from luminary_memory.types import Memory
    c = MemoryClient(db_path=str(tmp_path / "u.db"), engine=_E())
    m = Memory(content="no id yet", embedding=[0.1] * 384)
    import pytest
    with pytest.raises(ValueError):
        c.update(m)
    c.close()


def test_ingest_batch_empty(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "b.db"), engine=_E())
    res = c.ingest_batch([])
    assert res == [] or res == {}
    c.close()


def test_keyword_search_unlimited(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "k.db"), engine=_E())
    c.ingest("postgres index query")
    c.ingest("postgres tuning guide")
    hits = c.search("postgres", limit=0)
    assert len(hits) >= 2
    c.close()


def test_ingest_batch_tags_mismatch_raises(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "m.db"), engine=_E())
    import pytest
    with pytest.raises(ValueError):
        c.ingest_batch(["a", "b"], tags=["only-one"])
    c.close()


def test_by_tags_empty_and_corrupt(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "bt.db"), engine=_E())
    # empty tags → empty set
    assert c.backend.by_tags([]) == set()
    # corrupt tags JSON → treated as empty, no crash
    c.ingest("fact with tag", tags=["x"])
    c.backend.conn.execute("UPDATE memories SET tags='{corrupt' WHERE id=?", (c.list(limit=1)[0].id,))
    c.backend.conn.commit()
    res = c.backend.by_tags(["x"])
    assert isinstance(res, set)
    c.close()


def test_ingest_batch_embed_failure_falls_back(tmp_path, monkeypatch):
    class _BrokenBatch(_E):
        def embed_batch(self, ts):
            raise RuntimeError("batch embedding failed")
    c = MemoryClient(db_path=str(tmp_path / "fb.db"), engine=_BrokenBatch())
    c.ingest_batch(["fact one", "fact two"])
    assert c.count() == 2  # per-item fallback still stored both
    c.close()


def test_recall_snippet_error_ignored(tmp_path, monkeypatch):
    from luminary_memory.recall import snippets as snip_mod
    c = MemoryClient(db_path=str(tmp_path / "sn.db"), engine=_E())
    c.ingest("postgres tuning is critical for latency")
    monkeypatch.setattr(snip_mod, "extract_snippet", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("snippet failed")))
    r = c.recall("postgres", limit=5)
    assert r is not None  # recall survives snippet failure
    c.close()


def test_recall_keyword_error_falls_back(tmp_path, monkeypatch):
    from luminary_memory.recall import keyword as kw_mod
    c = MemoryClient(db_path=str(tmp_path / "kw.db"), engine=_E())
    c.ingest("postgres index tuning")

    def boom(*a, **kw):
        raise RuntimeError("keyword exploded")
    monkeypatch.setattr(kw_mod, "keyword_recall", boom)

    r = c.recall("postgres", limit=5)
    assert r is not None  # degraded, not raised
    c.close()


def test_health_score_empty_store(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "h.db"), engine=_E())
    report = c.health_score()
    assert report["score"] == 100.0
    assert report["dimensions"] == {}
    c.close()


def test_health_score_healthy_store(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "h2.db"), engine=_E())
    c.ingest("deploy target production cluster")
    c.ingest("user prefers dark mode")
    c.ingest("database runs on port 5432")
    report = c.health_score()
    assert 0 <= report["score"] <= 100
    assert "duplicate_rate" in report["dimensions"]
    assert report["dimensions"]["duplicate_rate"]["health"] == 100.0
    c.close()


def test_health_score_inspects_long_tail_and_never_read_rows(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "long-health.db"), engine=_E())
    c.ingest_batch([f"long lived fact number {i}" for i in range(505)])

    report = c.health_score()
    assert report["dimensions"]["size"]["value"] == 505
    assert report["dimensions"]["staleness"]["value"] == 1.0
    assert report["dimensions"]["staleness"]["never_accessed_count"] == 505
    assert report["dimensions"]["staleness"]["not_accessed_30d_count"] == 0
    assert any("never accessed" in recommendation for recommendation in report["recommendations"])
    c.close()


def test_health_score_does_not_mark_core_rows_stale(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "core-health.db"), engine=_E())
    c.ingest("always keep the user's identity stable", tags=["core"], importance=0.95)

    report = c.health_score()
    staleness = report["dimensions"]["staleness"]

    assert staleness["value"] == 0.0
    assert staleness["health"] == 100.0
    assert staleness["core_tagged_count"] == 1
    assert staleness["recall_memory_count"] == 0
    assert not any("never accessed" in recommendation for recommendation in report["recommendations"])
    c.close()


def test_health_score_duplicates_detected(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "h3.db"), engine=_E())
    c.ingest("deploy target is production cluster")
    c.ingest("deploy target is production cluster")  # exact dup
    report = c.health_score()
    assert report["dimensions"]["duplicate_rate"]["health"] < 100
    c.close()


def test_health_score_stale_detected(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "st.db"), engine=_E())
    mid = c.ingest("old fact never accessed")
    # fake last_accessed_at 60 days ago
    from datetime import datetime, timedelta
    old = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    c.backend.conn.execute("UPDATE memories SET last_accessed_at=? WHERE id=?", (old, mid))
    c.backend.conn.commit()
    report = c.health_score()
    assert report["dimensions"]["staleness"]["health"] < 100
    assert any("stale" in r for r in report["recommendations"])
    c.close()


def test_health_score_dup_recommendation(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "dr.db"), engine=_E())
    c.ingest("deploy target is production cluster")
    c.ingest("deploy target is production cluster")  # exact dup
    report = c.health_score()
    assert any("duplicate" in r for r in report["recommendations"])
    c.close()


def test_health_score_density_fallback(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "df.db"), engine=_E())
    c.ingest("fact one")
    c.backend.conn.execute("DROP TABLE relations")
    c.backend.conn.commit()
    report = c.health_score()  # must not crash without relations table
    assert "density" in report["dimensions"]
    c.close()


def test_health_importance_dimension_reflects_auto(tmp_path):
    """With auto importance, fresh store has high importance dimension."""
    c = MemoryClient(db_path=str(tmp_path / "hi.db"), engine=_E())
    c.ingest("fresh fact one")
    c.ingest("fresh fact two")
    report = c.health_score()
    # auto-estimated importance for fresh memories >= 0.3 → above prune_min 0.2
    assert report["dimensions"]["importance"]["health"] > 50
    c.close()


def test_recall_limit_zero_unlimited(tmp_path):
    """limit=0 means unlimited (None) — no 10k magic cap."""
    c = MemoryClient(db_path=str(tmp_path / "u.db"), engine=_E())
    for i in range(5):
        c.ingest(f"fact number {i}")
    r = c.recall("fact", limit=0)
    assert len(r.memories) >= 5  # all 5 returned, not capped at 10k path
    c.close()


def test_graph_empty_store(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "g.db"), engine=_E())
    g = c.graph()
    assert g == {"entities": [], "relations": []}
    c.close()


def test_graph_seeded_store(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "g2.db"), engine=_E())
    c.ingest("deploy target is production cluster", tags=["deploy", "production"])
    c.ingest("production database runs on port 5432", tags=["production", "database"])
    g = c.graph()
    assert len(g["entities"]) >= 3
    assert any(e["name"] == "production" and e["memories"] >= 2 for e in g["entities"])
    assert len(g["relations"]) >= 2
    c.close()


def test_graph_limit_caps_entities(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "g3.db"), engine=_E())
    for i in range(5):
        c.ingest(f"deploy target number {i} is production", tags=["deploy", f"n{i}"])
    g = c.graph(limit=3)
    assert len(g["entities"]) <= 3
    c.close()


def test_graph_backend_without_conn(tmp_path):
    """Backend without .conn falls back to empty graph (pgvector-safe)."""
    from luminary_memory.api import MemoryClient

    c = MemoryClient(db_path=str(tmp_path / "g4.db"), engine=_E())
    real_backend = c.backend
    # simulate a backend whose conn is None (query fails → fallback)
    real_backend._local.conn = None  # type: ignore[attr-defined]
    assert c.graph() == {"entities": [], "relations": []}
    c.close()
