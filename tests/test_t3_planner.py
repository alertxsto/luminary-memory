from luminary_memory.recall.planner import plan_strategies


def test_planner_all_enabled_when_has_entities():
    enabled = plan_strategies("deploy target", keyword_top_score=None, planner=True)
    assert enabled == frozenset({"semantic", "keyword", "temporal", "graph"})


def test_planner_skips_graph_when_no_entities():
    enabled = plan_strategies("!!!", keyword_top_score=None, planner=True)
    assert "graph" not in enabled
    assert {"semantic", "keyword", "temporal"} <= enabled


def test_planner_skips_temporal_on_strong_keyword_match():
    enabled = plan_strategies("deploy target", keyword_top_score=0.95, planner=True)
    assert "temporal" not in enabled


def test_planner_disabled_returns_all():
    enabled = plan_strategies("!!!", keyword_top_score=0.95, planner=False)
    assert enabled == frozenset({"semantic", "keyword", "temporal", "graph"})


def test_planner_never_skips_semantic_or_keyword():
    for q in ["!!!", "deploy target", ""]:
        for score in [None, 0.0, 0.99]:
            e = plan_strategies(q, keyword_top_score=score, planner=True)
            assert "semantic" in e
            assert "keyword" in e


def test_planner_graph_guard_exception_safe(monkeypatch):
    """Graph entity detection failing must not crash planning."""

    def boom(query):
        raise RuntimeError("graph unavailable")

    monkeypatch.setattr("luminary_memory.recall.graph._query_entities", boom)
    enabled = plan_strategies("deploy target", keyword_top_score=None, planner=True)
    # Exception is swallowed; all strategies stay enabled.
    assert enabled == frozenset({"semantic", "keyword", "temporal", "graph"})


def test_planner_temporal_guard_exception_safe(monkeypatch):
    """A non-numeric keyword score must not crash the temporal guard."""
    enabled = plan_strategies(
        "deploy target", keyword_top_score="not-a-number", planner=True
    )
    assert "temporal" in enabled
