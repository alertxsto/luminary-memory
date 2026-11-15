from __future__ import annotations

import statistics
import math


def recall_at_k(retrieved_ids: list[int], relevant_ids: set[int], k: int) -> float:
    if not relevant_ids:
        return 1.0
    topk = set(retrieved_ids[:k])
    return len(topk & relevant_ids) / len(relevant_ids)


def mrr(retrieved_ids: list[int], relevant_ids: set[int]) -> float:
    for rank, mid in enumerate(retrieved_ids, start=1):
        if mid in relevant_ids:
            return 1.0 / rank
    return 0.0


def cost_per_correct_answer(
    construction: float | None, query: float | None, correct_answers: int
) -> float | None:
    """Allocate a measured resource or monetary cost; missing is never zero."""
    if construction is None or query is None or correct_answers <= 0:
        return None
    return (construction + query) / correct_answers


def percentiles(latencies_ms: list[float]) -> dict[str, float | None]:
    if not latencies_ms:
        return {"p50": None, "p95": None, "mean": None}
    values = sorted(latencies_ms)

    def interpolate(quantile: float) -> float:
        position = quantile * (len(values) - 1)
        lower = math.floor(position)
        upper = math.ceil(position)
        return values[lower] + (values[upper] - values[lower]) * (position - lower)

    return {"p50": interpolate(0.5), "p95": interpolate(0.95), "mean": statistics.fmean(values)}
