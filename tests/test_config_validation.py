"""Reject invalid ranking configuration before it reaches recall."""

import pytest

from luminary_memory.config import Settings
from luminary_memory.recall.fusion import reciprocal_rank_fusion


@pytest.mark.parametrize(
    ("settings", "field"),
    [
        ({"rrf_k": -1}, "rrf_k"),
        ({"rrf_k": True}, "rrf_k"),
        ({"strategy_weights": {"semantic": float("nan")}}, "strategy_weights"),
        ({"strategy_weights": {"semantic": -0.1}}, "strategy_weights"),
        ({"strategy_weights": {"semantic": 0.0}}, "strategy_weights"),
        ({"recall_cliff_threshold": float("nan")}, "recall_cliff_threshold"),
        ({"recall_min_score": 1.1}, "recall_min_score"),
        ({"dedup_jaccard_threshold": -0.1}, "dedup_jaccard_threshold"),
        ({"abstention_min_confidence": -0.1}, "abstention_min_confidence"),
        ({"query_planner_keyword_threshold": 1.1}, "query_planner_keyword_threshold"),
        ({"token_budget": -1}, "token_budget"),
    ],
)
def test_settings_rejects_invalid_ranking_values(settings, field):
    with pytest.raises(ValueError, match=field):
        Settings(**settings)


def test_negative_rrf_env_is_rejected_during_settings_creation(monkeypatch):
    monkeypatch.setenv("LUMINARY_RRF_K", "-1")
    with pytest.raises(ValueError, match="rrf_k"):
        Settings()


def test_invalid_direct_fusion_constant_has_clear_error():
    with pytest.raises(ValueError, match="k"):
        reciprocal_rank_fusion([[1]], k=-1)
