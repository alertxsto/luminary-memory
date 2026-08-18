

def test_weighted_fusion_prefers_high_signal_strategy():
    """Semantic (weight 0.4) outranks temporal (0.1) at same rank."""
    from luminary_memory.recall.fusion import reciprocal_rank_fusion

    # memory 1 only in temporal at rank 0; memory 2 only in semantic at rank 0
    fused = reciprocal_rank_fusion(
        [[2], [1]],  # semantic list, temporal list
        strategy_labels=["semantic", "temporal"],
    )
    assert fused[0][0] == 2  # semantic (0.4) beats temporal (0.1)
    assert fused[0][1] > fused[1][1]


def test_weighted_fusion_labels_default_to_equal():
    """Without labels, fusion behaves like plain RRF (equal weights)."""
    from luminary_memory.recall.fusion import reciprocal_rank_fusion

    fused = reciprocal_rank_fusion([[1], [2]])
    assert fused[0][0] in (1, 2)
    assert abs(fused[0][1] - fused[1][1]) < 1e-9
