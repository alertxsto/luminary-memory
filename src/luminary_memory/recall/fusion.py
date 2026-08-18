from __future__ import annotations

# Per-strategy weights for fusion. Semantic and keyword carry the most signal
# (they actually match the query); graph is moderate; temporal is only
# recency/popularity, so it stays low to avoid surfacing "recent but
# irrelevant" memories.
STRATEGY_WEIGHTS: dict[str, float] = {
    "semantic": 0.4,
    "keyword": 0.3,
    "graph": 0.2,
    "temporal": 0.1,
}


def reciprocal_rank_fusion(
    ranked_lists: list[list[int]],
    k: int = 60,
    weights: dict[str, float] | None = None,
    strategy_labels: list[str] | None = None,
) -> list[tuple[int, float]]:
    """Weighted reciprocal rank fusion.

    Each strategy contributes ``weight / (k + rank)`` instead of the default
    ``1 / (k + rank)``, so high-signal strategies (semantic, keyword) dominate
    the fused ranking and low-signal ones (temporal) cannot push irrelevant
    recent memories to the top.
    """
    w = weights or STRATEGY_WEIGHTS
    scores: dict[int, float] = {}
    for i, lst in enumerate(ranked_lists):
        label = strategy_labels[i] if strategy_labels else None
        weight = w.get(label, 1.0) if label else 1.0
        for rank, mid in enumerate(lst):
            scores[mid] = scores.get(mid, 0.0) + weight / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])
