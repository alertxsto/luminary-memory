import pytest

from luminary_memory.recall.fusion import reciprocal_rank_fusion


def test_fused_ranking_collects_ids_from_all_strategies():
    lst_a = [1, 2, 3]
    lst_b = [3, 1, 4]
    fused = reciprocal_rank_fusion([lst_a, lst_b], k=60)
    ids = [mid for mid, _ in fused]
    assert set(ids) == {1, 2, 3, 4}


def test_multi_strategy_top_gets_highest_score():
    a = [1, 2, 3]
    b = [1, 3, 2]
    fused = reciprocal_rank_fusion([a, b], k=60)
    assert fused[0][0] == 1


def test_single_strategy_order_preserved():
    lst = [10, 20, 30]
    fused = reciprocal_rank_fusion([lst], k=60)
    assert [mid for mid, _ in fused] == [10, 20, 30]


def test_equal_weight_ties_keep_first_seen_strategy_order():
    lists = [[1, 2], [2, 1]]
    fused = reciprocal_rank_fusion(lists, k=60)
    assert [mid for mid, _ in fused] == [1, 2]
    assert [score for _, score in fused] == pytest.approx([1 / 61 + 1 / 62] * 2)


def test_rrf_k_changes_weighted_fractions_and_score_gap():
    lists = [[1, 2], [2, 1]]
    weights = {"semantic": 0.4, "keyword": 0.3}
    labels = ["semantic", "keyword"]
    small = dict(reciprocal_rank_fusion(lists, k=1, weights=weights, strategy_labels=labels))
    large = dict(reciprocal_rank_fusion(lists, k=60, weights=weights, strategy_labels=labels))
    assert small[1] == pytest.approx(0.4 / 2 + 0.3 / 3)
    assert small[2] == pytest.approx(0.4 / 3 + 0.3 / 2)
    assert large[1] == pytest.approx(0.4 / 61 + 0.3 / 62)
    assert large[2] == pytest.approx(0.4 / 62 + 0.3 / 61)
    assert small[1] - small[2] > large[1] - large[2] > 0


def test_empty_input_returns_empty():
    assert reciprocal_rank_fusion([], k=60) == []
    assert reciprocal_rank_fusion([[]], k=60) == []


def test_scores_are_positive_and_sorted_descending():
    fused = reciprocal_rank_fusion([[1, 2, 3], [3, 2, 1]], k=60)
    scores = [s for _, s in fused]
    assert all(s > 0 for s in scores)
    assert scores == sorted(scores, reverse=True)
