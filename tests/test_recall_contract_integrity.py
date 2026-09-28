"""Consumer-visible recall ordering, confidence, fallback and failure contracts."""

import hashlib
import logging
from datetime import UTC, datetime, timedelta
import logging

import pytest

from luminary_memory.api import MemoryClient
from luminary_memory.backends.sqlite import SQLiteBackend
from luminary_memory.config import Settings
from luminary_memory.recall.dedup import dedup_jaccard
from luminary_memory.recall.keyword import keyword_recall
from luminary_memory.recall.temporal import compute_temporal_score, temporal_recall
from luminary_memory.types import Memory


class _Engine:
    def embed(self, text):
        return [float(value) / 255 for value in hashlib.blake2b(text.encode(), digest_size=24).digest()]


class _BM25Backend(SQLiteBackend):
    def keyword_search(self, query, limit=10, **kwargs):
        rows = super().keyword_search(query, limit=limit, **kwargs)
        return [(memory, -1000.0 if i == 0 else 500.0) for i, (memory, _score) in enumerate(rows)]


def _client(tmp_path, **settings_kwargs):
    settings = Settings(db_path=str(tmp_path / "recall.db"), **settings_kwargs)
    return MemoryClient(settings=settings, engine=_Engine())


def test_m4_backend_score_scale_does_not_change_coverage_or_planner(tmp_path):
    backend = _BM25Backend(str(tmp_path / "recall.db"))
    client = MemoryClient(settings=Settings(db_path=str(tmp_path / "recall.db")),
                          backend=backend, engine=_Engine())
    full = client.ingest("postgres index")
    partial = client.ingest("postgres guide")
    rows = keyword_recall(backend, "postgres index", limit=None)
    assert [memory.id for memory, _, _ in rows] == [full, partial]
    assert [score for _, score, _ in rows] == [1.0, 0.5]
    result = client.recall("postgres index", limit=2)
    assert "temporal" not in result.strategies_hit  # full coverage suppresses recency noise
    client.close()


def test_m5_confidence_reranks_rrf_and_exposes_parallel_fused_scores(tmp_path, monkeypatch):
    client = _client(tmp_path, query_planner=False, recall_cliff_threshold=0.95,
                     rrf_k=1, strategy_weights={"semantic": 0.4, "keyword": 0.3,
                                                "temporal": 0.1, "graph": 0.2})
    partial = client.ingest("postgres guide")
    exact = client.ingest("postgres index")
    first, second = client.get(partial), client.get(exact)
    monkeypatch.setattr("luminary_memory.recall.semantic.semantic_recall",
                        lambda *a, **k: [(first, 0.5, "semantic"), (second, 0.5, "semantic")])
    monkeypatch.setattr("luminary_memory.recall.keyword.keyword_recall",
                        lambda *a, **k: [(first, 0.5, "keyword"), (second, 1.0, "keyword")])
    monkeypatch.setattr("luminary_memory.recall.temporal.temporal_recall",
                        lambda *a, **k: [(first, 0.5, "temporal"), (second, 0.5, "temporal")])
    monkeypatch.setattr("luminary_memory.recall.graph.graph_recall", lambda *a, **k: [])
    result = client.recall("postgres index", limit=2)
    assert [m.id for m in result.memories] == [exact, partial]
    assert result.scores[0] > result.scores[1]  # confidence, not RRF, sorts final output
    assert result.fused_scores == pytest.approx([0.8 / 3, 0.8 / 2])
    assert [item["fused_score"] for item in result.provenance] == pytest.approx(result.fused_scores)
    assert [item["confidence"] for item in result.provenance] == pytest.approx(result.scores)
    client.close()


def test_m10_min_score_filters_final_confidence_and_marks_empty(tmp_path):
    client = _client(tmp_path, recall_min_score=0.8, recall_cliff_threshold=0.95)
    exact = client.ingest("postgres index")
    client.ingest("postgres guide")
    result = client.recall("postgres index", limit=10)
    assert [m.id for m in result.memories] == [exact]
    assert len(result.scores) == len(result.fused_scores) == len(result.provenance) == 1
    client.settings.recall_min_score = 0.99
    memory = client.get(exact)
    memory.confidence = 0.6
    client.backend.update(memory)
    empty = client.recall("postgres index", limit=10)
    assert empty.memories == [] and empty.scores == []
    assert empty.status == "empty" and empty.reason == "below_min_score"
    client.close()


def test_m7_unlimited_dedup_keeps_candidates_beyond_comparison_window():
    rows = [(Memory(content=f"unique-{i}", id=i), 1.0) for i in range(501)]
    rows += [(Memory(content="unique-500", id=501), 0.5),
             (Memory(content="unique-502", id=502), 0.4)]
    retained = dedup_jaccard(rows)
    assert [m.id for m, _ in retained] == list(range(501)) + [502]


def test_m8_fallback_obeys_budget_limit_dedup_and_score_floor(tmp_path, monkeypatch):
    client = _client(tmp_path, query_planner=False, token_budget=2, recall_min_score=0.0)
    client.backend.add(Memory(content="alpha beta gamma", importance=0.9))
    client.backend.add(Memory(content="alpha beta gamma", importance=0.95))
    for module, method in (("semantic", "semantic_recall"), ("keyword", "keyword_recall"),
                           ("temporal", "temporal_recall"), ("graph", "graph_recall")):
        monkeypatch.setattr(f"luminary_memory.recall.{module}.{method}", lambda *a, **k: [])
    result = client.recall("unrelated query", limit=1)
    assert result.status == "empty" and result.reason == "token_budget_exhausted"
    assert result.memories == []  # neither three-token memory fits a two-token budget
    assert result.scores == []
    client.settings.token_budget = 10
    client.settings.recall_min_score = 0.2
    filtered = client.recall("unrelated query", limit=1)
    assert filtered.status == "empty" and filtered.reason == "below_min_score"
    assert filtered.memories == []
    client.settings.recall_min_score = 0
    selected = client.recall("unrelated query", limit=1)
    assert len(selected.memories) == len(selected.scores) == 1
    assert selected.memories[0].importance == pytest.approx(0.95)
    unlimited = client.recall("unrelated query", limit=0)
    assert len(unlimited.memories) == 1  # identical fallback rows deduplicate
    assert unlimited.scores == selected.scores
    unlimited = client.recall("unrelated query", limit=0)
    assert len(unlimited.memories) == 1  # identical fallback rows deduplicate
    assert unlimited.scores == selected.scores
    client.close()

def test_m8_temporal_fallback_uses_same_limit_floor_and_budget(tmp_path, monkeypatch):
    client = _client(tmp_path, query_planner=False, token_budget=2, recall_min_score=0.95)
    first = Memory(content="first memory", importance=0.1)
    second = Memory(content="second memory", importance=0.1)
    first.id = client.backend.add(first)
    second.id = client.backend.add(second)
    monkeypatch.setattr(client.backend, "top_by_importance", lambda **kwargs: [])
    for module, method in (("semantic", "semantic_recall"), ("keyword", "keyword_recall"),
                           ("graph", "graph_recall")):
        monkeypatch.setattr(f"luminary_memory.recall.{module}.{method}", lambda *a, **k: [])
    calls = 0

    def temporal(*args, **kwargs):
        nonlocal calls
        calls += 1
        return [] if calls % 2 else [(first, 10.0, "temporal"), (second, 9.0, "temporal")]

    monkeypatch.setattr("luminary_memory.recall.temporal.temporal_recall", temporal)
    result = client.recall("unknown topic", limit=1)
    assert result.status == "fallback" and result.reason == "temporal_fallback"
    assert [m.id for m in result.memories] == [first.id]
    assert result.scores == [1.0] and result.fused_scores == [None]
    assert len(result.provenance) == 1
    client.settings.token_budget = 1
    empty = client.recall("unknown topic", limit=1)
    assert empty.status == "empty" and empty.reason == "token_budget_exhausted"
    assert empty.memories == []
    client.close()



def test_m8_negative_access_counts_do_not_break_temporal_recall(tmp_path):
    client = _client(tmp_path)
    mid = client.ingest("a known fact")
    client.backend.conn.execute("UPDATE memories SET access_count=-5 WHERE id=?", (mid,))
    client.backend.conn.commit()
    memory = client.get(mid)
    assert 0 <= compute_temporal_score(memory) <= 1
    assert [row[0].id for row in temporal_recall(client.backend)] == [mid]
    client.close()


def test_m9_operational_search_failure_is_typed_and_recall_degrades(tmp_path, caplog):
    from luminary_memory.api import SearchError

    class _FailedKeyword(SQLiteBackend):
        def keyword_search(self, *args, **kwargs):
            raise RuntimeError("fts unavailable")

    backend = _FailedKeyword(str(tmp_path / "recall.db"))
    client = MemoryClient(settings=Settings(db_path=str(tmp_path / "recall.db"),
                                           query_planner=False), backend=backend, engine=_Engine())
    mid = client.ingest("postgres index")
    with pytest.raises(SearchError, match="fts unavailable"):
        client.search("postgres")
    with caplog.at_level(logging.ERROR, logger="luminary_memory.api"):
        result = client.recall("postgres index")
    assert mid in [memory.id for memory in result.memories]
    assert result.status == "degraded"
    assert "keyword" in (result.reason or "")
    assert "fts unavailable" in caplog.text
    client.close()


def test_m9_failed_all_strategies_is_error_not_successful_empty(tmp_path, monkeypatch):
    client = _client(tmp_path, query_planner=False)
    assert client.recall("postgres", strict=False).status == "empty"
    for module, method in (("semantic", "semantic_recall"), ("keyword", "keyword_recall"),
                           ("temporal", "temporal_recall"), ("graph", "graph_recall")):
        def fail(*args, **kwargs):
            raise RuntimeError("offline")
        monkeypatch.setattr(f"luminary_memory.recall.{module}.{method}", fail)
    result = client.recall("postgres", strict=False)
    assert result.status == "error"
    assert result.memories == []
    assert result.reason and "keyword" in result.reason
    client.close()

def test_m9_internal_typeerror_is_not_mistaken_for_legacy_signature(tmp_path):
    from luminary_memory.api import SearchError

    class _BrokenBackend(SQLiteBackend):
        def keyword_search(self, query, limit=10, scope=None, include_global=True):
            raise TypeError("fts decoder failure")

    backend = _BrokenBackend(str(tmp_path / "recall.db"))
    client = MemoryClient(backend=backend, settings=Settings(db_path=str(tmp_path / "recall.db")),
                          engine=_Engine())
    with pytest.raises(SearchError, match="fts decoder failure"):
        client.search("postgres")
    result = client.recall("postgres", strict=False)
    assert result.status == "error" and "keyword" in (result.reason or "")
    client.close()


def test_m9_legacy_search_signature_still_returns_ranked_results(tmp_path):
    class _LegacyBackend(SQLiteBackend):
        def keyword_search(self, query, limit=10):
            return super().keyword_search(query, limit=limit)

    backend = _LegacyBackend(str(tmp_path / "recall.db"))
    client = MemoryClient(backend=backend, settings=Settings(db_path=str(tmp_path / "recall.db")),
                          engine=_Engine())
    mid = client.ingest("postgres index")

def test_m9_legacy_search_filters_expired_candidates_before_top_k(tmp_path):
    class _LegacyBackend(SQLiteBackend):
        def keyword_search(self, query, limit=10):
            rows = [(memory, float(100 - memory.id)) for memory in self.all()]
            return rows if limit is None else rows[:limit]

    backend = _LegacyBackend(str(tmp_path / "recall.db"))
    client = MemoryClient(backend=backend, settings=Settings(db_path=str(tmp_path / "recall.db")),
                          engine=_Engine())
    backend.add(Memory(content="postgres expired",
                       valid_to=(datetime.now(UTC) - timedelta(days=1)).isoformat()))
    valid = backend.add(Memory(content="postgres current"))
    assert [memory.id for memory, _score in client.search("postgres", limit=1)] == [valid]
    assert [memory.id for memory, _score, _label in
            keyword_recall(backend, "postgres", limit=1)] == [valid]
    client.close()
    assert [m.id for m, _score in client.search("postgres")] == [mid]

def test_m9_legacy_search_filters_expired_candidates_before_top_k(tmp_path):
    class _LegacyBackend(SQLiteBackend):
        def keyword_search(self, query, limit=10):
            rows = [(memory, float(100 - memory.id)) for memory in self.all()]
            return rows if limit is None else rows[:limit]

    backend = _LegacyBackend(str(tmp_path / "recall.db"))
    client = MemoryClient(backend=backend, settings=Settings(db_path=str(tmp_path / "recall.db")),
                          engine=_Engine())
    backend.add(Memory(content="postgres expired",
                       valid_to=(datetime.now(UTC) - timedelta(days=1)).isoformat()))
    valid = backend.add(Memory(content="postgres current"))
    assert [memory.id for memory, _score in client.search("postgres", limit=1)] == [valid]
    assert [memory.id for memory, _score, _label in
            keyword_recall(backend, "postgres", limit=1)] == [valid]
    client.close()
    result = client.recall("postgres index")
    assert result.status == "ok" and result.memories[0].id == mid
    client.close()

def test_m9_internal_typeerror_is_not_mistaken_for_legacy_signature(tmp_path):
    from luminary_memory.api import SearchError

    class _BrokenBackend(SQLiteBackend):
        def keyword_search(self, query, limit=10, scope=None, include_global=True):
            raise TypeError("fts decoder failure")

    backend = _BrokenBackend(str(tmp_path / "recall.db"))
    client = MemoryClient(backend=backend, settings=Settings(db_path=str(tmp_path / "recall.db")),
                          engine=_Engine())
    with pytest.raises(SearchError, match="fts decoder failure"):
        client.search("postgres")
    result = client.recall("postgres", strict=False)
    assert result.status == "error" and "keyword" in (result.reason or "")
    client.close()


def test_m9_legacy_search_signature_still_returns_ranked_results(tmp_path):
    class _LegacyBackend(SQLiteBackend):
        def keyword_search(self, query, limit=10):
            return super().keyword_search(query, limit=limit)

    backend = _LegacyBackend(str(tmp_path / "recall.db"))
    client = MemoryClient(backend=backend, settings=Settings(db_path=str(tmp_path / "recall.db")),
                          engine=_Engine())
    mid = client.ingest("postgres index")
    assert [m.id for m, _score in client.search("postgres")] == [mid]
    result = client.recall("postgres index")
    assert result.status == "ok" and result.memories[0].id == mid
    client.close()
