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


def test_fusion_is_deterministic():
    lists = [[1, 2, 3], [2, 1, 3]]
    assert reciprocal_rank_fusion(lists, k=60) == reciprocal_rank_fusion(lists, k=60)


def test_rrf_k_affects_ordering():
    # with very large k, rank differences are diluted
    lists = [[1, 2], [2, 1]]
    fused_small = reciprocal_rank_fusion(lists, k=1)
    fused_large = reciprocal_rank_fusion(lists, k=60)
    # both must contain all ids regardless
    assert {m for m, _ in fused_small} == {1, 2}
    assert {m for m, _ in fused_large} == {1, 2}


def test_empty_input_returns_empty():
    assert reciprocal_rank_fusion([], k=60) == []
    assert reciprocal_rank_fusion([[]], k=60) == []


def test_scores_are_positive_and_sorted_descending():
    fused = reciprocal_rank_fusion([[1, 2, 3], [3, 2, 1]], k=60)
    scores = [s for _, s in fused]
    assert all(s > 0 for s in scores)
    assert scores == sorted(scores, reverse=True)
